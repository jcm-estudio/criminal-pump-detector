# 🚨 Criminal Pump Detector

Detector automatizado de Criminal/Scam Pumps en criptomonedas. Analiza datos de MEXC Exchange en tiempo real para identificar patrones de manipulación de precios.

**Costo total: $0.00 USD** — Usa exclusivamente servicios gratuitos.

## ⚡ Cómo funciona

```
MEXC API → Recolección de datos → Scoring (4 reglas) → Alertas Telegram
          (cada 15 min)          (automático)          (instantáneo)
```

### 4 Reglas de Detección

| Regla | Peso | Qué detecta |
|-------|------|-------------|
| 🔊 Volumen Anómalo | 30% | Volumen >200-300% vs promedio 7 días |
| 📈 Momentum de Precio | 30% | Subida temprana (+5% 1h, +15% 4h) |
| 💎 Eficiencia Market Cap | 20% | Market cap bajo + volumen desproporcionado |
| 🆕 Token Nuevo | 20% | Listado hace <7 días (manipulación máxima) |

### Niveles de Alerta

- 🔴 **CRITICO** (≥75): Alerta inmediata
- 🟠 **ALTO** (≥60): Alerta + monitoreo
- 🟡 **MEDIO** (≥45): Watchlist

## 🚀 Setup Rápido

### 1. Crear Bot de Telegram

1. En Telegram, buscar `@BotFather`
2. Enviar `/newbot` y seguir instrucciones
3. Guardar el **BOT_TOKEN**
4. Crear un grupo, agregar el bot
5. Visitar: `https://api.telegram.org/bot[TOKEN]/getUpdates`
6. Buscar `"chat":{"id":-123456789}` → ese es tu **CHAT_ID**

### 2. Configurar GitHub Secrets

En tu repo → Settings → Secrets and variables → Actions:

| Secret | Valor |
|--------|-------|
| `TELEGRAM_BOT_TOKEN` | El token de @BotFather |
| `TELEGRAM_CHAT_ID` | El ID del chat/grupo |

### 3. Push y listo

```bash
git add .
git commit -m "🚀 Deploy Criminal Pump Detector"
git push origin main
```

Los GitHub Actions se activarán automáticamente:
- **Discover**: 1x/día a las 3 AM UTC
- **Update**: Cada 15 minutos
- **Reporte**: 1x/día a las 9 AM UTC

## 📁 Estructura

```
criminal-pump-detector/
├── .github/workflows/     # GitHub Actions (cron jobs)
│   ├── discover.yml       # Escaneo diario
│   ├── update.yml         # Update cada 15 min
│   └── report.yml         # Reporte diario
├── src/
│   ├── config.py          # Configuración centralizada
│   ├── database.py        # SQLite schema + CRUD
│   ├── data_collector.py  # Recolección datos MEXC
│   ├── pump_scorer.py     # Motor de scoring (4 reglas)
│   └── alert_bot.py       # Alertas Telegram
├── tests/
│   └── test_pump_scorer.py
├── main.py                # Punto de entrada
└── requirements.txt
```

## 🧪 Ejecutar localmente

```bash
# Instalar dependencias
pip install -r requirements.txt

# Inicializar DB
python main.py init

# Escaneo completo
python main.py discover

# Update + scoring + alertas
python main.py update

# Probar alerta de Telegram
python -m src.alert_bot test
```

## 🛡️ Stack Gratuito

| Servicio | Función | Límite |
|----------|---------|--------|
| GitHub Actions | Cron jobs 24/7 | Ilimitado (repo público) |
| MEXC API | Datos de mercado | 10 req/s (público) |
| Telegram Bot | Alertas al celular | Ilimitado |
| SQLite | Base de datos | Sin límite |

## ⚠️ Disclaimer

Este software es **solo para fines educativos**. El trading de criptomonedas conlleva riesgos significativos. No inviertas dinero que no puedas permitirte perder. Los resultados pasados no garantizan resultados futuros.
