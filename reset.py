import os

# ✅ Cole a URL EXATA do Render aqui:
os.environ['DATABASE_URL'] = 'postgresql://pelada_db_pswz_user:ITCkNpKu0Z1yMZ61G4XN3RdVjxIUpAt3@dpg-d7tsb9ugvqtc73btpn20-a/pelada_db_pswz'

from app import app, db
from models import Admin
from werkzeug.security import generate_password_hash

with app.app_context():
    db.drop_all()
    db.create_all()
    print('✅ Banco recriado!')
    
    admin = Admin(
        username='admin',
        password=generate_password_hash('admin123')
    )
    db.session.add(admin)
    db.session.commit()
    print('✅ Admin criado: admin / admin123')