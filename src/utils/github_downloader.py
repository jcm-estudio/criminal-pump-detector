"""
Utilidad para descargar la base de datos de producción desde GitHub Artifacts.
Permite que el dashboard local siempre muestre los datos reales.
"""

import os
import subprocess
import shutil
import zipfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def ensure_gh_cli():
    """Verifica si el GitHub CLI está instalado."""
    try:
        subprocess.run(["gh", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except FileNotFoundError:
        return False

def is_gh_authenticated():
    """Verifica si el usuario está logueado en gh cli."""
    try:
        subprocess.run(["gh", "auth", "status"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def download_latest_db(repo_name="jcm-estudio/criminal-pump-detector", target_dir="data"):
    """
    Descarga el artifact 'pump-detector-db' más reciente.
    """
    if not ensure_gh_cli():
        logger.error("❌ GitHub CLI (gh) no está instalado. No se puede sincronizar la DB.")
        return False
        
    if not is_gh_authenticated():
        logger.error("❌ GitHub CLI no está autenticado. Corre 'gh auth login'.")
        return False
        
    Path(target_dir).mkdir(exist_ok=True)
    zip_path = Path(target_dir) / "db.zip"
    
    logger.info("🔄 Buscando el artifact más reciente en GitHub...")
    
    try:
        # 1. Obtener URL del último artifact
        cmd_get_url = [
            "gh", "api", f"repos/{repo_name}/actions/artifacts",
            "--jq", ".artifacts[] | select(.name==\"pump-detector-db\" and .expired==false) | .archive_download_url"
        ]
        
        result = subprocess.run(cmd_get_url, stdout=subprocess.PIPE, text=True, check=True)
        urls = result.stdout.strip().split('\n')
        
        if not urls or not urls[0]:
            logger.warning("⚠️ No se encontró ningún artifact válido en GitHub.")
            return False
            
        artifact_url = urls[0]
        
        # 2. Descargar el artifact
        logger.info(f"📥 Descargando DB desde producción...")
        subprocess.run(["gh", "api", artifact_url, ">", str(zip_path)], shell=True, check=True)
        
        # 3. Descomprimir
        if zip_path.exists() and zip_path.stat().st_size > 0:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
            logger.info("✅ Base de datos sincronizada con producción.")
            zip_path.unlink()
            return True
        else:
            logger.error("❌ El archivo descargado está vacío.")
            return False
            
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Error al comunicarse con GitHub: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}")
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    download_latest_db()
