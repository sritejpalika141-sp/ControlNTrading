import os
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger("encryption")

KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../master.key")
VAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../secrets.enc")

def _get_or_create_key() -> bytes:
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    
    # Generate new key
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    try:
        os.chmod(KEY_FILE, 0o400)
    except Exception:
        pass
        
    logger.warning("🚨 NEW MASTER ENCRYPTION KEY GENERATED. SAVE THIS SECURELY.")
    print(f"🚨 MASTER KEY GENERATED: {key.decode()} 🚨")
    return key

def encrypt_data(data: str) -> str:
    """Encrypts string data using the Master Key."""
    if not data:
        return data
    key = _get_or_create_key()
    f = Fernet(key)
    return f.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    """Decrypts string data using the Master Key."""
    if not encrypted_data:
        return encrypted_data
    try:
        key = _get_or_create_key()
        f = Fernet(key)
        return f.decrypt(encrypted_data.encode()).decode()
    except Exception as e:
        logger.error(f"Failed to decrypt data: {e}")
        return ""

def load_vault() -> dict:
    """Loads and decrypts the standalone secrets vault."""
    if not os.path.exists(VAULT_FILE):
        return {}
    try:
        with open(VAULT_FILE, "r") as f:
            lines = f.readlines()
        
        vault = {}
        for line in lines:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                vault[k] = decrypt_data(v)
        return vault
    except Exception as e:
        logger.error(f"Failed to load encrypted vault: {e}")
        return {}

def save_to_vault(key_name: str, plain_text_value: str):
    """Encrypts a value and saves it to the standalone vault."""
    vault = load_vault()
    vault[key_name] = plain_text_value
    
    try:
        with open(VAULT_FILE, "w") as f:
            for k, v in vault.items():
                enc_v = encrypt_data(v)
                f.write(f"{k}={enc_v}\n")
        try:
            os.chmod(VAULT_FILE, 0o600)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Failed to save to encrypted vault: {e}")

def get_secret(key_name: str, fallback_env: bool = True) -> str:
    """Gets a secret from the encrypted vault, falling back to OS environment."""
    vault = load_vault()
    if key_name in vault and vault[key_name]:
        return vault[key_name]
    if fallback_env:
        return os.getenv(key_name, "")
    return ""
