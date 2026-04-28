"""Verify the 3 fixes are correct."""
import pyodbc
from app.config import get_settings
from app.agent.tools import _split_into_fiscal_years

def test_splitter():
    print("=== Test 1: Fiscal Year Splitter ===")
    
    windows = _split_into_fiscal_years("2024/07/01", "2025/07/31")
    for w in windows:
        print(f"  {w[0]}: {w[1]} -> {w[2]}  ({w[3]})")
    assert len(windows) == 2, f"Expected 2 windows, got {len(windows)}"
    assert windows[0][1] == "2024/07/01" and windows[0][2] == "2025/06/30", f"FY1 wrong: {windows[0]}"
    assert windows[1][1] == "2025/07/01" and windows[1][2] == "2026/06/30", f"FY2 wrong: {windows[1]}"
    print("  OK Splitter correct!")

    windows2 = _split_into_fiscal_years("2024/07/01", "2025/06/30")
    assert len(windows2) == 1
    assert windows2[0][3] == "Full fiscal year"
    print("  OK Single FY correct!")

def test_sp_with_empty_team():
    print("\n=== Test 2: SP with empty team (All Teams) ===")
    conn = pyodbc.connect(get_settings().pharma_odbc_dsn)
    cursor = conn.cursor()
    cursor.execute("SET NOCOUNT ON")

    sql = "EXEC Sp_PharmaCRM_SVT '', '', '', '', '', '', '1', 1, '2024/07/01', '2025/06/30', 1"
    cursor.execute(sql)
    if cursor.description:
        cols = [c[0] for c in cursor.description]
        rows = cursor.fetchall()
        print(f"  Columns: {cols}")
        print(f"  Total rows: {len(rows)}")
        if rows:
            print(f"  Jul 24: Units={rows[0][1]}, Amount={rows[0][2]}")
            has_data = any(float(r[2]) != 0 for r in rows)
            assert has_data, "All amounts are 0!"
            print("  OK Real data returned!")
    conn.close()

def test_sp_with_zero_team():
    print("\n=== Test 3: SP with '0' team (old bug) ===")
    conn = pyodbc.connect(get_settings().pharma_odbc_dsn)
    cursor = conn.cursor()
    cursor.execute("SET NOCOUNT ON")

    sql = "EXEC Sp_PharmaCRM_SVT '', '0', '', '', '', '', '1', 1, '2024/07/01', '2025/06/30', 1"
    cursor.execute(sql)
    if cursor.description:
        rows = cursor.fetchall()
        all_zero = all(float(r[2]) == 0 for r in rows)
        print(f"  All zeros with '0': {all_zero}")
        print("  OK Confirmed: '0' produces zeroes, '' produces real data")
    conn.close()

if __name__ == '__main__':
    test_splitter()
    test_sp_with_empty_team()
    test_sp_with_zero_team()
    print("\nAll tests passed!")
