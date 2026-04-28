import pyodbc
from app.config import get_settings

def run():
    conn = pyodbc.connect(get_settings().pharma_odbc_dsn)
    cursor = conn.cursor()
    cursor.execute("SET NOCOUNT ON")
    
    cursor.execute("EXEC sp_helptext 'Sp_PharmaCRM_SVT'")
    lines = cursor.fetchall()
    with open('sp_helptext.sql', 'w', encoding='utf-8') as f:
        for row in lines:
            f.write(row[0])

if __name__ == '__main__':
    run()
