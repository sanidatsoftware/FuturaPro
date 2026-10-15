// FuturaPro - lettura dei file SQLite dei plugin (Info Prezzo, Info Ingredienti).
// Usa winsqlite3.dll, la libreria SQLite già presente in Windows 10/11: niente da installare.
// Lo compila code-totem.ps1 con Add-Type (C# 5, quello di Windows PowerShell 5.1).
using System;
using System.Collections;
using System.Runtime.InteropServices;
using System.Text;

public static class FpSqlite
{
    const string L = "winsqlite3.dll";
    const CallingConvention C = CallingConvention.StdCall;
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_open_v2(byte[] file, out IntPtr db, int flags, IntPtr vfs);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_close_v2(IntPtr db);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_busy_timeout(IntPtr db, int ms);
    [DllImport(L, CallingConvention = C)] static extern IntPtr sqlite3_errmsg(IntPtr db);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_prepare_v2(IntPtr db, byte[] sql, int n, out IntPtr stmt, IntPtr tail);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_step(IntPtr stmt);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_finalize(IntPtr stmt);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_bind_parameter_index(IntPtr stmt, byte[] name);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_bind_text(IntPtr stmt, int i, byte[] value, int n, IntPtr destructor);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_column_count(IntPtr stmt);
    [DllImport(L, CallingConvention = C)] static extern IntPtr sqlite3_column_name(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_column_type(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern long sqlite3_column_int64(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern double sqlite3_column_double(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern IntPtr sqlite3_column_text(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_column_bytes(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_exec(IntPtr db, byte[] sql, IntPtr callback, IntPtr arg, IntPtr errmsg);

    const int SOLA_LETTURA = 1, LETTURA_SCRITTURA = 2, RIGA = 100, FINE = 101;
    static readonly IntPtr COPIA = new IntPtr(-1); // SQLITE_TRANSIENT: SQLite copia il valore

    static byte[] Z(string s) { return Encoding.UTF8.GetBytes(s + "\0"); }

    static string Testo(IntPtr p, int n)
    {
        if (p == IntPtr.Zero) return null;
        if (n < 0) { n = 0; while (Marshal.ReadByte(p, n) != 0) n++; }
        byte[] b = new byte[n];
        Marshal.Copy(p, b, 0, n);
        return Encoding.UTF8.GetString(b);
    }

    static IntPtr Apri(string percorso, int modo)
    {
        IntPtr db;
        int rc = sqlite3_open_v2(Z(percorso), out db, modo, IntPtr.Zero);
        if (rc != 0)
        {
            string messaggio = db == IntPtr.Zero ? "codice " + rc : Testo(sqlite3_errmsg(db), -1);
            if (db != IntPtr.Zero) sqlite3_close_v2(db);
            throw new Exception("SQLite: " + messaggio);
        }
        sqlite3_busy_timeout(db, 2000);
        return db;
    }

    // La prima riga della query (o null), con i parametri «:nome» presenti nella query.
    public static Hashtable Cerca(string percorso, string sql, Hashtable parametri)
    {
        IntPtr db = Apri(percorso, SOLA_LETTURA);
        IntPtr st = IntPtr.Zero;
        try
        {
            if (sqlite3_prepare_v2(db, Z(sql), -1, out st, IntPtr.Zero) != 0)
                throw new Exception("Query non valida: " + Testo(sqlite3_errmsg(db), -1));
            foreach (DictionaryEntry p in parametri)
            {
                int i = sqlite3_bind_parameter_index(st, Z(":" + p.Key));
                if (i <= 0) continue;
                byte[] valore = Encoding.UTF8.GetBytes(Convert.ToString(p.Value));
                sqlite3_bind_text(st, i, valore, valore.Length, COPIA);
            }
            int rc = sqlite3_step(st);
            if (rc == FINE) return null;
            if (rc != RIGA) throw new Exception("Query: " + Testo(sqlite3_errmsg(db), -1));
            Hashtable riga = new Hashtable();
            int colonne = sqlite3_column_count(st);
            for (int c = 0; c < colonne; c++)
            {
                string nome = Testo(sqlite3_column_name(st, c), -1);
                switch (sqlite3_column_type(st, c))
                {
                    case 1: riga[nome] = sqlite3_column_int64(st, c); break;
                    case 2: riga[nome] = sqlite3_column_double(st, c); break;
                    case 5: riga[nome] = null; break;
                    default:
                        IntPtr t = sqlite3_column_text(st, c);
                        riga[nome] = Testo(t, sqlite3_column_bytes(st, c));
                        break;
                }
            }
            return riga;
        }
        finally
        {
            if (st != IntPtr.Zero) sqlite3_finalize(st);
            sqlite3_close_v2(db);
        }
    }

    // Sulla copia locale: riporta nel file le modifiche rimaste nel «-wal», così poi si apre in sola lettura.
    public static void SenzaWal(string percorso)
    {
        IntPtr db = Apri(percorso, LETTURA_SCRITTURA);
        try { sqlite3_exec(db, Z("PRAGMA journal_mode=DELETE"), IntPtr.Zero, IntPtr.Zero, IntPtr.Zero); }
        finally { sqlite3_close_v2(db); }
    }
}
