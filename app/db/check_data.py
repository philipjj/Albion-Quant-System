import sqlite3

def check_malformed():
    conn = sqlite3.connect("data/albion_quant.db")
    cursor = conn.cursor()
    
    # 1. Check for double T in ARTEFACT
    cursor.execute("SELECT item_id FROM items WHERE item_id LIKE '%ARTEFACT%'")
    rows = cursor.fetchall()
    if rows:
        print(f"Sample ARTEFACT IDs ({len(rows)} found):")
        for r in rows[:20]:
            print(f" - {r[0]}")
    else:
        print("No ARTEFACT IDs found.")
        
    conn.close()

if __name__ == "__main__":
    check_malformed()
