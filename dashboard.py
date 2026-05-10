"""
Dashboard Interactivo para Criminal Pump Detector.
Construido con Streamlit, se conecta a la base de datos de producción (vía GitHub Artifacts).
"""

import sys
from pathlib import Path
import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Asegurar que los imports del proyecto funcionen
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.utils.github_downloader import download_latest_db
from src.config import DB_PATH

# ============================================================
# CONFIGURACIÓN PÁGINA
# ============================================================

st.set_page_config(
    page_title="Criminal Pump Detector",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🤖 Criminal Pump Detector")
st.markdown("Dashboard interactivo con datos de producción.")

# ============================================================
# DATOS
# ============================================================

@st.cache_data(ttl=300) # Refrescar cada 5 min
def load_data():
    """Descarga la DB de producción y carga los dataframes."""
    with st.spinner("Sincronizando base de datos desde GitHub (producción)..."):
        # Descarga el artifact. Si falla, usará la DB local si existe.
        download_latest_db()
        
    if not DB_PATH.exists():
        st.error("No se encontró la base de datos. Asegúrate de tener permisos en GitHub.")
        st.stop()
        
    conn = sqlite3.connect(DB_PATH)
    
    # Cargar tablas
    try:
        df_trades = pd.read_sql_query("""
            SELECT pt.*, t.symbol 
            FROM paper_trades pt 
            JOIN tokens t ON pt.token_id = t.id
            ORDER BY pt.entry_time DESC
        """, conn)
        
        df_signals = pd.read_sql_query("""
            SELECT s.*, t.symbol 
            FROM signals s 
            JOIN tokens t ON s.token_id = t.id
            ORDER BY s.timestamp DESC
            LIMIT 500
        """, conn)
        
        df_weights = pd.read_sql_query("""
            SELECT * FROM learning_weights
        """, conn)
        
    except Exception as e:
        st.error(f"Error leyendo DB: {e}")
        st.stop()
    finally:
        conn.close()
        
    # Procesar fechas
    if not df_trades.empty:
        df_trades['entry_time'] = pd.to_datetime(df_trades['entry_time']).dt.tz_localize('UTC')
        if 'exit_time' in df_trades.columns:
            df_trades['exit_time'] = pd.to_datetime(df_trades['exit_time']).dt.tz_localize('UTC')
            
    if not df_signals.empty:
        df_signals['timestamp'] = pd.to_datetime(df_signals['timestamp']).dt.tz_localize('UTC')
        
    return df_trades, df_signals, df_weights

df_trades, df_signals, df_weights = load_data()

# ============================================================
# TABS
# ============================================================

tab1, tab2, tab3 = st.tabs(["📊 Métricas (Paper Trading)", "📝 Historial de Trades", "🧠 Learning Engine"])

with tab1:
    st.header("Rendimiento del Algoritmo")
    
    if df_trades.empty:
        st.info("Aún no hay operaciones registradas en el simulador.")
    else:
        # Métricas clave
        col1, col2, col3, col4 = st.columns(4)
        
        closed_trades = df_trades[df_trades['status'] == 'CLOSED']
        open_trades = df_trades[df_trades['status'] == 'OPEN']
        
        total_pnl = closed_trades['pnl_usd'].sum() if not closed_trades.empty else 0
        total_trades = len(closed_trades)
        win_trades = len(closed_trades[closed_trades['pnl_usd'] > 0])
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        
        col1.metric("PNL Total (Simulado)", f"${total_pnl:.2f}")
        col2.metric("Win Rate", f"{win_rate:.1f}%")
        col3.metric("Trades Cerrados", total_trades)
        col4.metric("Posiciones Abiertas", len(open_trades))
        
        st.markdown("---")
        
        # Gráficos
        col_graf1, col_graf2 = st.columns(2)
        
        with col_graf1:
            st.subheader("Evolución del PNL")
            if not closed_trades.empty:
                # Ordenar cronológicamente para la curva acumulada
                df_chron = closed_trades.sort_values('exit_time').copy()
                df_chron['cum_pnl'] = df_chron['pnl_usd'].cumsum()
                
                fig = px.line(df_chron, x='exit_time', y='cum_pnl', markers=True,
                              labels={'exit_time': 'Fecha de Cierre', 'cum_pnl': 'PNL Acumulado ($)'})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("No hay suficientes datos.")
                
        with col_graf2:
            st.subheader("Distribución de Ganancias/Pérdidas")
            if not closed_trades.empty:
                fig = px.histogram(closed_trades, x='pnl_usd', nbins=20, 
                                   color='exit_reason',
                                   labels={'pnl_usd': 'Resultado del Trade ($)'})
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("No hay suficientes datos.")

with tab2:
    st.header("Historial de Operaciones")
    if df_trades.empty:
        st.info("Sin operaciones.")
    else:
        # Filtros
        status_filter = st.selectbox("Estado", ["TODOS", "OPEN", "CLOSED"])
        if status_filter != "TODOS":
            display_df = df_trades[df_trades['status'] == status_filter]
        else:
            display_df = df_trades
            
        # Formatear tabla para mostrar
        show_cols = ['symbol', 'status', 'entry_price', 'exit_price', 'pnl_percent', 'pnl_usd', 'exit_reason', 'entry_time']
        display_df = display_df[show_cols].copy()
        
        # Ocultar nulos en trades abiertos
        display_df['pnl_percent'] = display_df['pnl_percent'].apply(lambda x: f"{x:+.2f}%" if pd.notnull(x) else "-")
        display_df['pnl_usd'] = display_df['pnl_usd'].apply(lambda x: f"${x:+.2f}" if pd.notnull(x) else "-")
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)

with tab3:
    st.header("🧠 Inteligencia del Bot (Pesos Actuales)")
    st.markdown("""
    El *Learning Engine* corre una vez por semana evaluando los trades cerrados. 
    Aumenta el peso de las reglas que dieron ganancias y disminuye el de las que generaron pérdidas.
    """)
    
    if df_weights.empty:
        st.info("Aún no hay pesos registrados.")
    else:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.dataframe(df_weights[['rule_name', 'weight', 'last_updated']], hide_index=True)
            
        with col2:
            # Gráfico Radial de pesos
            fig = px.line_polar(df_weights, r='weight', theta='rule_name', line_close=True,
                                markers=True, title="Distribución de Pesos de las Reglas")
            fig.update_traces(fill='toself')
            st.plotly_chart(fig, use_container_width=True)
