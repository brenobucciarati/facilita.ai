/**
 * ==========================================
 * PELADA FC - Inscrição JavaScript
 * Funções para a página pública de inscrição
 * ==========================================
 */

// Variáveis
var dadosPessoa = null;

// Obtém código do evento da URL
var pathParts = window.location.pathname.split('/');
var CODIGO_EVENTO = pathParts[pathParts.length - 1];

// Elementos do DOM
var matriculaInput = document.getElementById('matricula');
var btnInscrever = document.getElementById('btn-inscrever');
var nomeRetorno = document.getElementById('nome-retorno');
var mensagemDiv = document.getElementById('mensagem');

// ==================== EVENTOS ====================

// Input de matrícula
if (matriculaInput) {
    matriculaInput.addEventListener('input', async function(e) {
        var matricula = e.target.value.replace(/\D/g, '');
        
        // Garante 6 dígitos com zeros à esquerda
        if (matricula.length > 0) {
            matricula = matricula.padStart(6, '0');
        }
        
        if (matricula.length === 6) {
            await validarMatricula(matricula);
        } else {
            limparValidacao();
        }
    });
    
    // Permite apenas números
    matriculaInput.addEventListener('keypress', function(e) {
        if (!/[0-9]/.test(e.key)) {
            e.preventDefault();
        }
    });
}

// Botão de inscrever
if (btnInscrever) {
    btnInscrever.addEventListener('click', async function() {
        if (!dadosPessoa) return;
        
        var matricula = matriculaInput.value.replace(/\D/g, '').padStart(6, '0');
        
        // Mostrar loading
        this.disabled = true;
        this.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Inscrevendo...';
        
        try {
            var response = await fetch('/api/inscrever', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    codigo_evento: CODIGO_EVENTO,
                    matricula: matricula
                })
            });
            
            var data = await response.json();
            
            if (data.sucesso) {
                if (mensagemDiv) {
                    mensagemDiv.innerHTML = 
                        '<div class="alert alert-success">' + data.mensagem + '</div>';
                }
                
                // Atualiza contador de vagas
                var vagasDisponiveis = document.getElementById('vagas-disponiveis');
                if (vagasDisponiveis) {
                    vagasDisponiveis.textContent = data.vagas_restantes + ' vagas';
                }
                
                // Se esgotou as vagas
                if (data.vagas_restantes <= 0) {
                    var formInscricao = document.getElementById('form-inscricao');
                    var vagasEsgotadas = document.getElementById('vagas-esgotadas');
                    
                    if (formInscricao) formInscricao.style.display = 'none';
                    if (vagasEsgotadas) vagasEsgotadas.style.display = 'block';
                } else {
                    limparValidacao();
                    if (matriculaInput) matriculaInput.value = '';
                }
            } else {
                if (mensagemDiv) {
                    mensagemDiv.innerHTML = 
                        '<div class="alert alert-danger">' + (data.mensagem || 'Erro ao inscrever') + '</div>';
                }
            }
        } catch (error) {
            console.error('Erro ao inscrever:', error);
            if (mensagemDiv) {
                mensagemDiv.innerHTML = 
                    '<div class="alert alert-danger">Erro de conexão. Tente novamente.</div>';
            }
        } finally {
            // Restaurar botão
            this.disabled = false;
            this.innerHTML = '✓ CONFIRMAR INSCRIÇÃO';
        }
    });
}

// ==================== FUNÇÕES ====================

/**
 * Valida a matrícula na API
 */
async function validarMatricula(matricula) {
    try {
        var response = await fetch('/api/validar-matricula', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                codigo_evento: CODIGO_EVENTO,
                matricula: matricula
            })
        });
        
        var data = await response.json();
        
        if (data.valido) {
            dadosPessoa = data;
            
            // Mostrar informações
            if (nomeRetorno) {
                nomeRetorno.style.display = 'block';
            }
            
            var nomePessoa = document.getElementById('nome-pessoa');
            var funcaoPessoa = document.getElementById('funcao-pessoa');
            
            if (nomePessoa) nomePessoa.textContent = data.nome;
            if (funcaoPessoa) funcaoPessoa.textContent = data.funcao;
            
            if (btnInscrever) btnInscrever.disabled = false;
            if (mensagemDiv) mensagemDiv.innerHTML = '';
            
            // Atualiza vagas
            var vagasDisponiveis = document.getElementById('vagas-disponiveis');
            if (vagasDisponiveis) {
                vagasDisponiveis.textContent = data.vagas_restantes + ' vagas';
            }
            
            // Feedback visual positivo
            if (matriculaInput) {
                matriculaInput.style.borderColor = '#10b981';
                matriculaInput.style.boxShadow = '0 0 0 4px rgba(16, 185, 129, 0.1)';
            }
        } else {
            limparValidacao();
            
            if (mensagemDiv) {
                var html = '<div class="alert alert-danger">' + data.mensagem + '</div>';
                
                if (data.pode_cancelar) {
                    html += 
                        '<button class="btn btn-warning btn-sm w-100 mt-2" onclick="cancelarInscricao(' + data.inscricao_id + ')">' +
                        '<i class="fas fa-times-circle"></i> Cancelar minha inscrição' +
                        '</button>';
                }
                
                mensagemDiv.innerHTML = html;
            }
            
            // Feedback visual negativo
            if (matriculaInput) {
                matriculaInput.style.borderColor = '#ef4444';
                matriculaInput.style.boxShadow = '0 0 0 4px rgba(239, 68, 68, 0.1)';
            }
        }
    } catch (error) {
        console.error('Erro ao validar:', error);
        limparValidacao();
        
        if (mensagemDiv) {
            mensagemDiv.innerHTML = 
                '<div class="alert alert-danger">Erro ao validar matrícula. Tente novamente.</div>';
        }
    }
}

/**
 * Cancela uma inscrição existente
 */
async function cancelarInscricao(inscricaoId) {
    if (!confirm('Deseja realmente cancelar sua inscrição?')) return;
    
    try {
        var response = await fetch('/api/cancelar-inscricao', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({inscricao_id: inscricaoId})
        });
        
        var data = await response.json();
        
        if (data.sucesso) {
            location.reload();
        } else {
            alert('Erro ao cancelar inscrição. Tente novamente.');
        }
    } catch (error) {
        console.error('Erro ao cancelar:', error);
        alert('Erro de conexão. Verifique sua internet.');
    }
}

/**
 * Limpa o formulário de validação
 */
function limparValidacao() {
    dadosPessoa = null;
    
    if (nomeRetorno) nomeRetorno.style.display = 'none';
    if (btnInscrever) btnInscrever.disabled = true;
    
    // Resetar borda do input
    if (matriculaInput) {
        matriculaInput.style.borderColor = '';
        matriculaInput.style.boxShadow = '';
    }
}

/**
 * Atualiza contador de vagas
 */
function atualizarContadorVagas(restantes, total) {
    var vagasDisponiveis = document.getElementById('vagas-disponiveis');
    if (vagasDisponiveis) {
        vagasDisponiveis.textContent = restantes + ' vagas';
    }
}

// ==================== INICIALIZAÇÃO ====================

console.log('%c⚽ Pelada FC %c- Página de Inscrição',
    'color: #10b981; font-weight: bold;',
    'color: #94a3b8;');