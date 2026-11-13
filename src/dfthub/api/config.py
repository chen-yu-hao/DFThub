from dfthub.paths import data_dir, load_environment
import os
load_environment()
DATA_DIR_IS_OVERRIDE = bool(os.environ.get('DFTHUB_DATA_DIR'))
DATA_DIR = data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
