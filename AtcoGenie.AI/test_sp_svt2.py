import pyodbc
from app.config import get_settings

def run():
    conn = pyodbc.connect(get_settings().pharma_odbc_dsn)
    cursor = conn.cursor()
    cursor.execute("SET NOCOUNT ON")

    print('Testing with GroupId=Product')
    sql = "EXEC Sp_PharmaCRM_SVT 'Product', '0', '', '', '', '', '1', 1, '2024/07/01', '2025/06/30', 1"
    cursor.execute(sql)
    if cursor.description:
        cols = [c[0] for c in cursor.description]
        print('Columns:', cols)
        rows = cursor.fetchall()
        print('Rows:', len(rows))
        if rows:
            print('Sample:', rows[0])
    
    print('\\nTesting with GroupId=3 (usually product)')
    sql = "EXEC Sp_PharmaCRM_SVT '3', '0', '', '', '', '', '1', 1, '2024/07/01', '2025/06/30', 1"
    cursor.execute(sql)
    if cursor.description:
        cols = [c[0] for c in cursor.description]
        print('Columns:', cols)
        rows = cursor.fetchall()
        print('Rows:', len(rows))
        if rows:
            print('Sample:', rows[0])

    print('\\nTesting with MonthID=0')
    sql = "EXEC Sp_PharmaCRM_SVT '', '0', '', '', '', '', '1', 1, '2024/07/01', '2025/06/30', 0"
    cursor.execute(sql)
    if cursor.description:
        cols = [c[0] for c in cursor.description]
        print('Columns:', cols)
        rows = cursor.fetchall()
        print('Rows:', len(rows))
        if rows:
            print('Sample:', rows[0])

if __name__ == '__main__':
    run()
