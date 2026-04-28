import pyodbc
from app.config import get_settings

def run():
    conn = pyodbc.connect(get_settings().pharma_odbc_dsn)
    cursor = conn.cursor()

    cursor.execute("SET NOCOUNT ON")

    print('Calling Sp_PharmaCRM_SVT for FY2024/2025...')
    sql = (
        "EXEC Sp_PharmaCRM_SVT "
        "'', "
        "'0', "
        "'', "
        "'', "
        "'', "
        "'', "
        "'1', "
        "1, "
        "'2024/07/01', "
        "'2025/06/30', "
        "1"
    )
    cursor.execute(sql)

    if not cursor.description:
        print("No description. Try nextset...")
        while cursor.nextset():
            if cursor.description:
                break
                
    if cursor.description:
        cols = [column[0] for column in cursor.description]
        print('Columns:', cols)

        rows = cursor.fetchall()
        print('Total Rows:', len(rows))

        if rows:
            sample = rows[0]
            print('Sample Row:', sample)
            
            rev_cols = [c for c in cols if 'net' in c.lower() or 'revenue' in c.lower() or 'sales' in c.lower() or 'value' in c.lower()]
            print('Revenue columns:', rev_cols)
            
            for rev_col in rev_cols:
                idx = cols.index(rev_col)
                non_zero = sum(1 for r in rows if r[idx] and float(r[idx]) != 0)
                print(f'{rev_col} -> non-zero count: {non_zero}')
    else:
        print("Still no description")

if __name__ == '__main__':
    run()
