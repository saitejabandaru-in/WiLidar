import os
import zipfile
from datetime import datetime
from server.utils.config import settings
from server.utils.logger import logger


def perform_backup():
    """
    Backs up the SQLite database and all files in the models directory.
    Stores the backup in a timestamped ZIP archive inside the backups folder,
    and removes any backups older than 30 days.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_{timestamp}.zip"
    backup_path = os.path.join(settings.BACKUPS_DIR, backup_filename)

    logger.info("Starting scheduled system backup...")

    try:
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            # 1. Backup SQLite Database
            db_path = settings.SQLITE_PATH
            if os.path.exists(db_path):
                logger.info(f"Archiving SQLite database: {db_path}")
                zipf.write(db_path, arcname=os.path.basename(db_path))
            else:
                logger.warning("SQLite database file not found during backup.")

            # 2. Backup Models Directory
            models_dir = settings.MODELS_DIR
            if os.path.exists(models_dir):
                logger.info(f"Archiving models folder: {models_dir}")
                for root, dirs, files in os.walk(models_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Relative path in zip file
                        rel_path = os.path.relpath(
                            file_path, os.path.dirname(models_dir)
                        )
                        zipf.write(file_path, arcname=rel_path)
            else:
                logger.warning("Models directory not found during backup.")

        logger.info(f"Backup successfully written to: {backup_path}")

        # 3. Clean up backups older than 30 days
        cleanup_old_backups()

    except Exception as e:
        logger.error(f"Backup failed: {str(e)}", exc_info=True)


def cleanup_old_backups(keep_days: int = 30):
    """
    Removes ZIP files in the backup folder older than keep_days.
    """
    try:
        now = datetime.now()
        backups = [
            f
            for f in os.listdir(settings.BACKUPS_DIR)
            if f.startswith("backup_") and f.endswith(".zip")
        ]

        for backup in backups:
            backup_path = os.path.join(settings.BACKUPS_DIR, backup)
            file_time = datetime.fromtimestamp(os.path.getmtime(backup_path))
            age_days = (now - file_time).days

            if age_days > keep_days:
                logger.info(f"Deleting expired backup: {backup} (Age: {age_days} days)")
                os.remove(backup_path)

    except Exception as e:
        logger.error(f"Failed to clean up old backups: {str(e)}")


if __name__ == "__main__":
    perform_backup()
