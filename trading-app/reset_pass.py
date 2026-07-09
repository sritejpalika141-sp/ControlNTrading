import sqlite3
import bcrypt

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

conn = sqlite3.connect('trading_app.db')
c = conn.cursor()
new_hash = hash_password("admin123")
c.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (new_hash,))
conn.commit()
conn.close()
print("Password reset successfully to admin123")
