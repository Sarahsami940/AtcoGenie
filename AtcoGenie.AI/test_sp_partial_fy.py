import pyodbc
from app.config import get_settings

def run():
    conn = pyodbc.connect(get_settings().pharma_odbc_dsn)
    cursor = conn.cursor()
    cursor.execute("SET NOCOUNT ON")

    print('Testing partial FY: 2025/07/01 to 2025/07/31')
    sql = "EXEC Sp_PharmaCRM_SVT '', '', '', '', '', '', '1', 1, '2025/07/01', '2025/07/31', 1"
    try:
        cursor.execute(sql)
        if cursor.description:
            rows = cursor.fetchall()
            print('Rows:', len(rows))
            if rows:
                print('Sample:', rows[0])
    except Exception as e:
        print('ERROR:', str(e))

if __name__ == '__main__':
    run()
