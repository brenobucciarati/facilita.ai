"""
==========================================
PELADA FC - Backup e Atualização do Banco
==========================================
Uso: python backup_update.py
Opções:
  - Sem argumentos: Faz backup + atualiza tabelas
  - --backup-only: Apenas backup
  - --update-only: Apenas atualizar tabelas
  - --restore [arquivo]: Restaura um backup
  - --list: Lista backups disponíveis
==========================================
"""

import shutil
import datetime
import os
import sys

# ==================== CONFIGURAÇÃO ====================
DB_PATH = 'instance/pelada.db'  # Caminho do banco principal
BACKUP_DIR = 'instance/backups'  # Pasta de backups
DATE_FORMAT = '%Y%m%d_%H%M%S'

# ==================== FUNÇÕES ====================

def criar_backup():
    """Cria um backup do banco de dados atual"""
    if not os.path.exists(DB_PATH):
        print(f'❌ Banco não encontrado em: {DB_PATH}')
        return None
    
    # Criar pasta de backups
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    # Nome do backup com data/hora
    timestamp = datetime.datetime.now().strftime(DATE_FORMAT)
    nome_backup = f'backup_pelada_{timestamp}.db'
    caminho_backup = os.path.join(BACKUP_DIR, nome_backup)
    
    # Copiar arquivo
    shutil.copy2(DB_PATH, caminho_backup)
    
    # Tamanho
    tamanho = os.path.getsize(caminho_backup)
    tamanho_kb = tamanho / 1024
    
    print(f'✅ Backup criado: {nome_backup}')
    print(f'   Caminho: {caminho_backup}')
    print(f'   Tamanho: {tamanho_kb:.1f} KB')
    
    return caminho_backup


def atualizar_tabelas():
    """Atualiza/cria tabelas no banco de dados"""
    try:
        from app import app, db
        with app.app_context():
            db.create_all()
            tabelas = [t.name for t in db.metadata.sorted_tables]
            print(f'✅ Tabelas atualizadas com sucesso!')
            print(f'   Tabelas existentes: {", ".join(tabelas)}')
    except Exception as e:
        print(f'❌ Erro ao atualizar tabelas: {str(e)}')


def listar_backups():
    """Lista todos os backups disponíveis"""
    if not os.path.exists(BACKUP_DIR):
        print('📂 Nenhum backup encontrado.')
        return []
    
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')],
        reverse=True
    )
    
    if not backups:
        print('📂 Nenhum backup encontrado.')
        return []
    
    print('📋 Backups disponíveis:')
    print('=' * 70)
    for i, bkp in enumerate(backups, 1):
        caminho = os.path.join(BACKUP_DIR, bkp)
        tamanho = os.path.getsize(caminho) / 1024
        data_hora = bkp.replace('backup_pelada_', '').replace('.db', '')
        data = f'{data_hora[:4]}-{data_hora[4:6]}-{data_hora[6:8]}'
        hora = f'{data_hora[9:11]}:{data_hora[11:13]}:{data_hora[13:15]}'
        print(f'[{i}] {bkp}')
        print(f'    Data: {data} {hora} | Tamanho: {tamanho:.1f} KB')
        print('-' * 70)
    
    return backups


def restaurar_backup(nome_arquivo):
    """Restaura um backup específico"""
    caminho_backup = os.path.join(BACKUP_DIR, nome_arquivo)
    
    if not os.path.exists(caminho_backup):
        # Tenta encontrar com parte do nome
        matches = [f for f in os.listdir(BACKUP_DIR) if nome_arquivo in f]
        if len(matches) == 1:
            caminho_backup = os.path.join(BACKUP_DIR, matches[0])
        elif len(matches) > 1:
            print('❌ Múltiplos backups encontrados. Especifique melhor:')
            for m in matches:
                print(f'   - {m}')
            return
        else:
            print(f'❌ Backup não encontrado: {nome_arquivo}')
            return
    
    # Confirmar restauração
    print(f'⚠️  ATENÇÃO: Isso substituirá o banco atual!')
    confirmacao = input(f'   Restaurar {os.path.basename(caminho_backup)}? (s/n): ')
    
    if confirmacao.lower() != 's':
        print('❌ Restauração cancelada.')
        return
    
    # Criar backup do estado atual antes de restaurar
    if os.path.exists(DB_PATH):
        criar_backup()
    
    # Restaurar
    shutil.copy2(caminho_backup, DB_PATH)
    print(f'✅ Banco restaurado com sucesso!')


def limpar_backups_antigos(manter=5):
    """Mantém apenas os últimos N backups"""
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')]
    )
    
    if len(backups) <= manter:
        print(f'✅ Apenas {len(backups)} backups. Nada a limpar.')
        return
    
    for bkp in backups[:-manter]:
        os.remove(os.path.join(BACKUP_DIR, bkp))
        print(f'🗑️  Removido: {bkp}')
    
    print(f'✅ Mantidos os {manter} backups mais recentes.')


# ==================== PRINCIPAL ====================

def main():
    print('=' * 70)
    print('⚽ PELADA FC - Backup & Atualização do Banco de Dados')
    print('=' * 70)
    
    args = sys.argv[1:]
    
    # Modo interativo (sem argumentos)
    if not args:
        print('\nEscolha uma opção:')
        print('[1] Backup + Atualizar tabelas (recomendado)')
        print('[2] Apenas fazer backup')
        print('[3] Apenas atualizar tabelas')
        print('[4] Listar backups')
        print('[5] Restaurar backup')
        print('[6] Limpar backups antigos')
        print('[0] Sair')
        
        opcao = input('\n➡️  Opção: ').strip()
        
        if opcao == '1':
            print('\n📦 Fazendo backup...')
            criar_backup()
            print('\n⬆️  Atualizando tabelas...')
            atualizar_tabelas()
        elif opcao == '2':
            print('\n📦 Fazendo backup...')
            criar_backup()
        elif opcao == '3':
            print('\n⬆️  Atualizando tabelas...')
            atualizar_tabelas()
        elif opcao == '4':
            listar_backups()
        elif opcao == '5':
            backups = listar_backups()
            if backups:
                num = input('\n➡️  Número do backup (ou nome): ').strip()
                if num.isdigit() and 1 <= int(num) <= len(backups):
                    restaurar_backup(backups[int(num) - 1])
                else:
                    restaurar_backup(num)
        elif opcao == '6':
            n = input('\n➡️  Manter quantos backups? (padrão 5): ').strip()
            manter = int(n) if n.isdigit() else 5
            limpar_backups_antigos(manter)
        elif opcao == '0':
            print('👋 Até logo!')
        else:
            print('❌ Opção inválida!')
        
        print('\n' + '=' * 70)
        return
    
    # Modo linha de comando
    if '--backup-only' in args:
        criar_backup()
    elif '--update-only' in args:
        atualizar_tabelas()
    elif '--restore' in args:
        idx = args.index('--restore') + 1
        if idx < len(args):
            restaurar_backup(args[idx])
        else:
            print('❌ Especifique o arquivo de backup: --restore [arquivo]')
    elif '--list' in args:
        listar_backups()
    elif '--clean' in args:
        limpar_backups_antigos()
    else:
        # Padrão: backup + atualizar
        criar_backup()
        print()
        atualizar_tabelas()
    
    print('\n' + '=' * 70)


if __name__ == '__main__':
    main()