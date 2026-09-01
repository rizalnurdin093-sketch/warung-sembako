"""Database layer — Warung Sembako. SQLite, pattern sama seperti Surat Tugas."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'warung.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Produk
    c.execute("""
        CREATE TABLE IF NOT EXISTS produk (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            satuan TEXT NOT NULL DEFAULT 'pcs',
            harga_beli INTEGER NOT NULL DEFAULT 0,
            harga_jual INTEGER NOT NULL DEFAULT 0,
            stok INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Transaksi penjualan (1 baris per produk; group_id mengelompokkan 1 pembelian)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_produk TEXT NOT NULL,
            harga_satuan INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            total INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            kasir TEXT,
            group_id INTEGER,
            bayar INTEGER,
            kembalian INTEGER
        )
    """)
    # Users (owner / kasir)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'kasir',
            nama TEXT
        )
    """)
    # Setoran kas harian (anti-kecurangan: kas teoretis vs setoran riil)
    c.execute("""
        CREATE TABLE IF NOT EXISTS setoran (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal TEXT NOT NULL,
            jumlah INTEGER NOT NULL,
            catatan TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # Opname stok (anti-kecurangan: stok sistem vs stok fisik)
    c.execute("""
        CREATE TABLE IF NOT EXISTS opname (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal TEXT NOT NULL,
            produk_id INTEGER NOT NULL,
            stok_fisik INTEGER NOT NULL,
            stok_sistem INTEGER NOT NULL,
            selisih INTEGER NOT NULL,
            catatan TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (produk_id) REFERENCES produk(id)
        )
    """)
    # Seed user default (owner + kasir) bila belum ada
    if c.execute("SELECT COUNT(*) FROM users WHERE username='owner'").fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password, role, nama) VALUES (?,?,?,?)",
                  ('owner', 'password', 'owner', 'Rizal (Owner)'))
    if c.execute("SELECT COUNT(*) FROM users WHERE username='kasir'").fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password, role, nama) VALUES (?,?,?,?)",
                  ('kasir', 'password', 'kasir', 'Karyawan'))
    conn.commit()
    conn.close()

    _migrate_group_id()


def _migrate_group_id():
    """
    Migrasi Opsi A: pastikan kolom group_id ada di trasaksi. Data lama
    (tanpa group_id) di-assign group_id = id (tiap baris = 1 pembelian terisolasi).
    """
    conn = get_db()
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(transaksi)").fetchall()]
    new_cols = [c for c in ('group_id', 'bayar', 'kembalian') if c not in cols]
    for c in new_cols:
        cur.execute(f"ALTER TABLE transaksi ADD COLUMN {c} INTEGER")
    # Data lama: group_id = id kalau NULL
    cur.execute("UPDATE transaksi SET group_id = id WHERE group_id IS NULL")
    conn.commit()
    conn.close()

def produk_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM produk ORDER BY nama").fetchall()
    conn.close()
    return rows

def produk_add(nama, satuan, harga_beli, harga_jual, stok):
    conn = get_db()
    conn.execute("INSERT INTO produk (nama, satuan, harga_beli, harga_jual, stok) VALUES (?,?,?,?,?)",
                 (nama, satuan, harga_beli, harga_jual, stok))
    conn.commit()
    conn.close()

def produk_delete(pid):
    conn = get_db()
    conn.execute("DELETE FROM produk WHERE id=?", (pid,))
    conn.commit()
    conn.close()

def stok_kurang(pid, qty):
    conn = get_db()
    conn.execute("UPDATE produk SET stok = stok - ? WHERE id=?", (qty, pid))
    conn.commit()
    conn.close()

def transaksi_buat(cart, kasir, bayar=None):
    """
    Opsi A: buat 1 pembelian (group) berisi beberapa item. Setiap item = 1 baris
    di tabel transaksi, semua baris punya group_id yang sama. Kurangi stok tiap item.
    cart: list of dict {'produk_id', 'nama', 'harga_jual', 'qty'}
    Return: (group_id, total)
    """
    conn = get_db()
    cur = conn.cursor()
    total = sum(item['harga_jual'] * item['qty'] for item in cart)

    bayar_int = int(bayar) if bayar and str(bayar).strip() else None
    kembalian = (bayar_int - total) if bayar_int is not None else None
    if bayar_int is not None and bayar_int < total:
        conn.close()
        raise ValueError("Uang bayar kurang dari total")

    # Ambil id terbesar sebagai group_id berikutnya
    row = cur.execute("SELECT COALESCE(MAX(group_id), 0) AS m FROM transaksi").fetchone()
    gid = row['m'] + 1

    for item in cart:
        cur.execute(
            "INSERT INTO transaksi (nama_produk, harga_satuan, qty, total, kasir, group_id, bayar, kembalian) VALUES (?,?,?,?,?,?,?,?)",
            (item['nama'], item['harga_jual'], item['qty'], item['harga_jual'] * item['qty'],
             kasir, gid, bayar_int, kembalian)
        )
        cur.execute("UPDATE produk SET stok = stok - ? WHERE id=?", (item['qty'], item['produk_id']))

    conn.commit()
    conn.close()
    return gid, total

def rekap_harian():
    conn = get_db()
    rows = conn.execute("""
        SELECT created_at AS hari,
               SUM(total) AS total,
               COUNT(DISTINCT group_id) AS jumlah_transaksi,
               SUM(qty) AS total_item
        FROM transaksi
        GROUP BY date(created_at)
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return rows

# ===== USERS =====
def user_find(username):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return row

def user_add(username, password, role, nama):
    conn = get_db()
    conn.execute("INSERT INTO users (username, password, role, nama) VALUES (?,?,?,?)",
                 (username, password, role, nama))
    conn.commit()
    conn.close()

def user_list():
    conn = get_db()
    rows = conn.execute("SELECT id, username, role, nama FROM users ORDER BY id").fetchall()
    conn.close()
    return rows

# ===== SETORAN (anti-kecurangan kas) =====
def setoran_today(tanggal):
    conn = get_db()
    row = conn.execute("SELECT SUM(jumlah) AS total FROM setoran WHERE tanggal=?", (tanggal,)).fetchone()
    conn.close()
    return row['total'] or 0

def setoran_add(tanggal, jumlah, catatan):
    conn = get_db()
    conn.execute("INSERT INTO setoran (tanggal, jumlah, catatan) VALUES (?,?,?)",
                 (tanggal, jumlah, catatan))
    conn.commit()
    conn.close()

def setoran_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM setoran ORDER BY tanggal DESC, id DESC").fetchall()
    conn.close()
    return rows

# ===== OPNAME (anti-kecurangan stok) =====
def opname_add(tanggal, produk_id, stok_fisik, stok_sistem, catatan):
    selisih = stok_fisik - stok_sistem
    conn = get_db()
    conn.execute("""INSERT INTO opname (tanggal, produk_id, stok_fisik, stok_sistem, selisih, catatan)
                    VALUES (?,?,?,?,?,?)""",
                 (tanggal, produk_id, stok_fisik, stok_sistem, selisih, catatan))
    conn.commit()
    conn.close()

def opname_list():
    conn = get_db()
    rows = conn.execute("""
        SELECT o.*, p.nama AS nama_produk
        FROM opname o LEFT JOIN produk p ON o.produk_id = p.id
        ORDER BY o.tanggal DESC, o.id DESC
    """).fetchall()
    conn.close()
    return rows

# ===== KAS TEORETIS (total penjualan per tanggal) =====
def omzet_by_date(tanggal):
    """Total penjualan (kas teoretis) untuk tanggal tertentu."""
    conn = get_db()
    row = conn.execute("SELECT SUM(total) AS total FROM transaksi WHERE date(created_at)=?", (tanggal,)).fetchone()
    conn.close()
    return row['total'] or 0

# ===== AUDIT LOG (histori transaksi detail per kasir) =====
def transaksi_all():
    conn = get_db()
    rows = conn.execute("""
        SELECT id, created_at, nama_produk, harga_satuan, qty, total, kasir, group_id
        FROM transaksi ORDER BY created_at DESC, id DESC
    """).fetchall()
    conn.close()
    return rows

def rekap_per_kasir():
    """Total penjualan per kasir (jumlah pembeli = distinct group_id)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT COALESCE(kasir, 'tanpa-nama') AS kasir,
               SUM(total) AS total,
               COUNT(DISTINCT group_id) AS jumlah_transaksi
        FROM transaksi
        GROUP BY COALESCE(kasir, 'tanpa-nama')
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return rows

# ===== GRAFIK PENJUALAN =====
def grafik_omzet_harian(hari=30):
    """Total omzet per hari (N hari terakhir)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT date(created_at) AS tgl,
               SUM(total) AS total,
               COUNT(*) AS jumlah
        FROM transaksi
        GROUP BY date(created_at)
        ORDER BY date(created_at) DESC
        LIMIT ?
    """, (hari,)).fetchall()
    conn.close()
    return list(reversed(rows))  # urut ASC

def grafik_penjualan_produk():
    """Total penjualan per produk (nama + qty terjual)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT nama_produk AS nama,
               SUM(qty) AS qty,
               SUM(total) AS total
        FROM transaksi
        GROUP BY nama_produk
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return rows

# ===== STOK RENDAH (deteksi + alert) =====
def stok_rendah():
    """Produk dengan stok < 5."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM produk WHERE stok < 5 ORDER BY stok ASC, nama").fetchall()
    conn.close()
    return rows


def backup_blob():
    """Buat salinan DB sebagai bytes (untuk download)."""
    import sqlite3
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(':memory:')
    src.backup(dst)  # konsisten snapshot
    buf = dst.serialize()  # bytes SQLite format
    src.close()
    dst.close()
    return buf

def restore_blob(data):
    """Ganti DB dengan data backup (bytes)."""
    import sqlite3
    # tulis sementara ke bytes, lalu load ke DB path
    tmp = sqlite3.connect(':memory:')
    tmp.deserialize(data)
    dst = sqlite3.connect(DB_PATH)
    tmp.backup(dst)
    tmp.close()
    dst.close()

init_db()
