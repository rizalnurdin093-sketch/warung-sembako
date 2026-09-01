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
    # Transaksi penjualan (HEADER — 1 baris per struk/pembeli)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kasir TEXT,
            total INTEGER NOT NULL DEFAULT 0,
            bayar INTEGER,
            kembalian INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # Detail transaksi (ITEM — 1 baris per produk dalam struk)
    c.execute("""
        CREATE TABLE IF NOT EXISTS detail_transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaksi_id INTEGER NOT NULL,
            produk_id INTEGER,
            nama_produk TEXT NOT NULL,
            harga_satuan INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            FOREIGN KEY (transaksi_id) REFERENCES transaksi(id)
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

    # ==== MIGRASI: transaksi lama (1 baris = 1 produk) -> header + detail =====
    _migrate_transaksi()


def _migrate_transaksi():
    """
    Migrasi data lama dari skema transaksi-produk tunggal ke skema baru
    (transaksi header + detail_transaksi item).

    Deteksi: jika tabel transaksi masih punya kolom 'nama_produk'/'qty'
    (skema lama), pindahkan tiap baris -> 1 header + 1 detail, lalu
    drop kolom lama (rebuild tabel).
    """
    conn = get_db()
    cur = conn.cursor()
    # Matikan FK constraint selama migrasi (rename/drop tabel)
    cur.execute("PRAGMA foreign_keys = OFF")
    # Cek kolom transaksi
    cols = [r[1] for r in cur.execute("PRAGMA table_info(transaksi)").fetchall()]
    if 'nama_produk' not in cols:
        # Sudah skema baru, tidak usah migrasi
        conn.close()
        return

    # Ambil semua transaksi lama
    old_rows = conn.execute(
        "SELECT id, nama_produk, harga_satuan, qty, total, created_at, kasir FROM transaksi"
    ).fetchall()

    # Backup file lama dulu
    _backup_before_migrate()

    # Rename tabel lama -> simpan, buat tabel baru, isi ulang
    cur.execute("ALTER TABLE transaksi RENAME TO transaksi_old")
    conn.commit()

    # Recreate tabel baru (skema header)
    cur.execute("""
        CREATE TABLE transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kasir TEXT,
            total INTEGER NOT NULL DEFAULT 0,
            bayar INTEGER,
            kembalian INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    # Recreate detail_transaksi: DROP dulu karena FK lama menunjuk transaksi_old
    cur.execute("DROP TABLE IF EXISTS detail_transaksi")
    cur.execute("""
        CREATE TABLE detail_transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaksi_id INTEGER NOT NULL,
            produk_id INTEGER,
            nama_produk TEXT NOT NULL,
            harga_satuan INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            FOREIGN KEY (transaksi_id) REFERENCES transaksi(id)
        )
    """)

    # Isi ulang: each old row -> 1 header + 1 detail
    for r in old_rows:
        cur.execute(
            "INSERT INTO transaksi (id, kasir, total, created_at) VALUES (?,?,?,?)",
            (r['id'], r['kasir'], r['total'], r['created_at'])
        )
        cur.execute(
            "INSERT INTO detail_transaksi (transaksi_id, nama_produk, harga_satuan, qty, subtotal) VALUES (?,?,?,?,?)",
            (r['id'], r['nama_produk'], r['harga_satuan'], r['qty'], r['total'])
        )
    conn.commit()

    # Hapus tabel lama
    cur.execute("DROP TABLE transaksi_old")
    conn.commit()
    conn.close()


def _backup_before_migrate():
    """Buat salinan DB ke file backup_*.db sebelum migrasi (jaga-jaga)."""
    import datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = DB_PATH + f".backup_{stamp}"
    import shutil
    try:
        shutil.copyfile(DB_PATH, dst)
    except Exception:
        pass

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
    Buat 1 transaksi (struk) berisi beberapa item + kurangi stok.
    cart: list of dict {'produk_id', 'nama', 'harga_jual', 'qty', 'stok'}
    Return: (transaksi_id, total)
    """
    conn = get_db()
    cur = conn.cursor()
    total = sum(item['harga_jual'] * item['qty'] for item in cart)

    # Bayar/kembalian
    bayar_int = int(bayar) if bayar and str(bayar).strip() else None
    kembalian = (bayar_int - total) if bayar_int is not None else None
    if bayar_int is not None and bayar_int < total:
        conn.close()
        raise ValueError("Uang bayar kurang dari total")

    cur.execute(
        "INSERT INTO transaksi (kasir, total, bayar, kembalian) VALUES (?,?,?,?)",
        (kasir, total, bayar_int, kembalian)
    )
    tid = cur.lastrowid

    for item in cart:
        subtotal = item['harga_jual'] * item['qty']
        cur.execute(
            """INSERT INTO detail_transaksi
               (transaksi_id, produk_id, nama_produk, harga_satuan, qty, subtotal)
               VALUES (?,?,?,?,?,?)""",
            (tid, item['produk_id'], item['nama'], item['harga_jual'], item['qty'], subtotal)
        )
        cur.execute("UPDATE produk SET stok = stok - ? WHERE id=?",
                    (item['qty'], item['produk_id']))

    conn.commit()
    conn.close()
    return tid, total

def rekap_harian():
    conn = get_db()
    rows = conn.execute("""
        SELECT t.created_at AS hari,
               SUM(t.total) AS total,
               COUNT(t.id) AS jumlah_transaksi,
               COALESCE(SUM(d.qty), 0) AS total_item
        FROM transaksi t
        LEFT JOIN detail_transaksi d ON d.transaksi_id = t.id
        GROUP BY date(t.created_at)
        ORDER BY t.created_at DESC
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
    """Semua baris transaksi header (satu per struk) — untuk log & export."""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, created_at, kasir, total, bayar, kembalian
        FROM transaksi ORDER BY created_at DESC, id DESC
    """).fetchall()
    conn.close()
    return rows


def transaksi_detail(transaksi_id):
    """Item-item dalam satu transaksi (untuk lihat isi struk)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT transaksi_id, nama_produk, harga_satuan, qty, subtotal
        FROM detail_transaksi WHERE transaksi_id=? ORDER BY id
    """, (transaksi_id,)).fetchall()
    conn.close()
    return rows

def rekap_per_kasir():
    """Total penjualan per kasir."""
    conn = get_db()
    rows = conn.execute("""
        SELECT COALESCE(kasir, 'tanpa-nama') AS kasir,
               SUM(total) AS total,
               COUNT(id) AS jumlah_transaksi
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
               COUNT(id) AS jumlah
        FROM transaksi
        GROUP BY date(created_at)
        ORDER BY date(created_at) DESC
        LIMIT ?
    """, (hari,)).fetchall()
    conn.close()
    return list(reversed(rows))  # urut ASC

def grafik_penjualan_produk():
    """Total penjualan per produk (nama + qty terjual) dari detail_transaksi."""
    conn = get_db()
    rows = conn.execute("""
        SELECT nama_produk AS nama,
               SUM(qty) AS qty,
               SUM(subtotal) AS total
        FROM detail_transaksi
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
