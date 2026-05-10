import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import database as db

def inject_fake_pump():
    """Inyecta un pump falso en la base de datos para pruebas."""
    db.init_db()
    
    with db.get_db() as conn:
        # Tomar el primer token activo
        token = conn.execute("SELECT id, symbol FROM tokens LIMIT 1").fetchone()
        token_id = token["id"]
        symbol = token["symbol"]
        
        now = datetime.now(timezone.utc)
        
        # Eliminar historial viejo de este token
        conn.execute("DELETE FROM price_data WHERE token_id = ?", (token_id,))
        conn.execute("DELETE FROM metrics WHERE token_id = ?", (token_id,))
        
        # Insertar precios viejos (precio base 1.0, volumen bajo)
        for i in range(10, 0, -1):
            past_time = (now - timedelta(hours=i)).isoformat()
            conn.execute(
                "INSERT INTO price_data (token_id, timestamp, price, volume_24h) VALUES (?, ?, ?, ?)",
                (token_id, past_time, 1.0, 10000)
            )
            
        # Insertar precio actual (pump masivo: precio 1.5 (+50%), volumen 100000 (+1000%))
        conn.execute(
            "INSERT INTO price_data (token_id, timestamp, price, volume_24h) VALUES (?, ?, ?, ?)",
            (token_id, now.isoformat(), 1.5, 100000)
        )
        
        print(f"✅ Inyectado pump falso en {symbol} (Token ID: {token_id})")
        print(f"   Precio base: 1.0 -> Precio actual: 1.5")
        print(f"   Volumen base: 10K -> Volumen actual: 100K")

if __name__ == "__main__":
    inject_fake_pump()
