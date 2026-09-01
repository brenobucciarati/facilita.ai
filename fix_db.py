from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE inscricao ADD COLUMN jogador_id INTEGER REFERENCES jogadores(id)"))
        db.session.commit()
        print("✅ Coluna jogador_id adicionada com sucesso!")
    except Exception as e:
        print(f"⚠️ Erro: {e}")