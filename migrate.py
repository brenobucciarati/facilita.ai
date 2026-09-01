from app import app, db
from sqlalchemy import text
import os

print("🚀 INICIANDO MIGRAÇÕES...")

with app.app_context():
    print("📊 Verificando tabelas...")
    db.create_all()
    
    is_postgres = app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql://')
    
    migrations = [
        ("inscricao", "jogador_id", "INTEGER"),
        ("evento", "vagas_mensalistas", "INTEGER DEFAULT 0"),
        ("evento", "vagas_diaristas", "INTEGER DEFAULT 0"),
        ("evento", "vagas_visitantes", "INTEGER DEFAULT 0"),
        ("evento", "usar_prioridades", "BOOLEAN DEFAULT FALSE"),
    ]
    
    for tabela, coluna, tipo in migrations:
        try:
            if is_postgres:
                db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {coluna} {tipo}"))
            else:
                # SQLite
                result = db.session.execute(text(f"PRAGMA table_info({tabela})")).fetchall()
                colunas_existentes = [row[1] for row in result]
                if coluna not in colunas_existentes:
                    db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}"))
            print(f"✅ {tabela}.{coluna} OK")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print(f"⏭️ {tabela}.{coluna} já existe")
            else:
                print(f"⚠️ {tabela}.{coluna}: {e}")
    
    db.session.commit()
    print("✅ MIGRAÇÕES CONCLUÍDAS!")