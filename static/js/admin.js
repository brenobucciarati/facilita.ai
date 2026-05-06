/**
 * ==========================================
 * PELADA FC - Admin JavaScript
 * Funções compartilhadas entre telas admin
 * ==========================================
 */

// ==================== CONFIGURAÇÃO ====================
var API_BASE = window.location.origin;

// ==================== UTILITÁRIOS ====================

/**
 * Formata data para DD/MM/YYYY
 */
function formatarData(data) {
    if (!data) return '';
    var d = new Date(data);
    var dia = String(d.getDate()).padStart(2, '0');
    var mes = String(d.getMonth() + 1).padStart(2, '0');
    var ano = d.getFullYear();
    return dia + '/' + mes + '/' + ano;
}

/**
 * Formata data e hora para DD/MM/YYYY HH:MM
 */
function formatarDataHora(data) {
    if (!data) return '';
    var d = new Date(data);
    var dia = String(d.getDate()).padStart(2, '0');
    var mes = String(d.getMonth() + 1).padStart(2, '0');
    var ano = d.getFullYear();
    var hora = String(d.getHours()).padStart(2, '0');
    var min = String(d.getMinutes()).padStart(2, '0');
    return dia + '/' + mes + '/' + ano + ' ' + hora + ':' + min;
}

/**
 * Formata tamanho de arquivo
 */
function formatarTamanho(bytes) {
    if (bytes === 0) return '0 Bytes';
    var k = 1024;
    var sizes = ['Bytes', 'KB', 'MB', 'GB'];
    var i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Debounce para evitar múltiplas chamadas
 */
function debounce(func, wait) {
    var timeout;
    return function() {
        var context = this;
        var args = arguments;
        clearTimeout(timeout);
        timeout = setTimeout(function() {
            func.apply(context, args);
        }, wait);
    };
}

// ==================== NOTIFICAÇÕES TOAST ====================

/**
 * Exibe uma notificação toast
 * @param {string} mensagem - Texto da notificação
 * @param {string} tipo - success, error, warning, info
 * @param {number} duracao - Tempo em ms (padrão 4000)
 */
function mostrarToast(mensagem, tipo, duracao) {
    tipo = tipo || 'success';
    duracao = duracao || 4000;
    
    // Criar container se não existir
    var container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 
            'position: fixed; top: 20px; right: 20px; z-index: 99999; ' +
            'display: flex; flex-direction: column; gap: 10px; pointer-events: none;';
        document.body.appendChild(container);
    }
    
    var cores = {
        success: '#10b981',
        error: '#ef4444',
        warning: '#f59e0b',
        info: '#3b82f6'
    };
    
    var icones = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    
    var toast = document.createElement('div');
    toast.style.cssText = 
        'background: #1a2332; border: 1px solid ' + cores[tipo] + '40; ' +
        'border-left: 4px solid ' + cores[tipo] + '; color: #e2e8f0; ' +
        'padding: 14px 20px; border-radius: 12px; display: flex; align-items: center; ' +
        'gap: 12px; font-weight: 500; font-size: 0.9em; font-family: Inter, sans-serif; ' +
        'box-shadow: 0 10px 40px rgba(0,0,0,0.5); pointer-events: auto; ' +
        'animation: toastIn 0.3s ease forwards; min-width: 300px; max-width: 450px; ' +
        'cursor: pointer; transition: all 0.3s ease;';
    
    toast.innerHTML = 
        '<i class="fas ' + icones[tipo] + '" style="color: ' + cores[tipo] + '; font-size: 1.2em; flex-shrink: 0;"></i>' +
        '<span style="flex: 1;">' + mensagem + '</span>' +
        '<i class="fas fa-times" style="color: #64748b; font-size: 0.8em; cursor: pointer; flex-shrink: 0;"></i>';
    
    toast.addEventListener('click', function() {
        removerToast(toast);
    });
    
    container.appendChild(toast);
    
    // Auto remover
    var timeout = setTimeout(function() {
        removerToast(toast);
    }, duracao);
    
    // Guardar referência do timeout
    toast._timeout = timeout;
}

function removerToast(toast) {
    if (toast._removendo) return;
    toast._removendo = true;
    
    clearTimeout(toast._timeout);
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100px)';
    
    setTimeout(function() {
        if (toast.parentNode) {
            toast.remove();
        }
    }, 300);
}

// Adicionar animação CSS para toast
var toastStyle = document.createElement('style');
toastStyle.textContent = 
    '@keyframes toastIn { ' +
    '  from { opacity: 0; transform: translateX(100px); } ' +
    '  to { opacity: 1; transform: translateX(0); } ' +
    '}';
document.head.appendChild(toastStyle);

// ==================== CONFIRMAÇÃO ====================

/**
 * Diálogo de confirmação personalizado
 */
function confirmarAcao(mensagem, callback) {
    if (confirm(mensagem)) {
        if (typeof callback === 'function') {
            callback();
        }
        return true;
    }
    return false;
}

/**
 * Confirmação com callback assíncrono
 */
async function confirmarAcaoAsync(mensagem, callback) {
    if (confirm(mensagem)) {
        if (typeof callback === 'function') {
            await callback();
        }
        return true;
    }
    return false;
}

// ==================== LOADING ====================

/**
 * Mostra loading em um botão
 */
function mostrarLoading(botao) {
    if (!botao) return;
    botao.disabled = true;
    botao.setAttribute('data-texto-original', botao.innerHTML);
    botao.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Aguarde...';
    botao.classList.add('loading');
}

/**
 * Restaura botão após loading
 */
function esconderLoading(botao) {
    if (!botao) return;
    botao.disabled = false;
    var textoOriginal = botao.getAttribute('data-texto-original');
    if (textoOriginal) {
        botao.innerHTML = textoOriginal;
    }
    botao.classList.remove('loading');
}

// ==================== MODAL ====================

/**
 * Abre modal do Bootstrap
 */
function abrirModal(idModal) {
    var modalEl = document.getElementById(idModal);
    if (!modalEl) return;
    
    var modal = new bootstrap.Modal(modalEl);
    modal.show();
}

/**
 * Fecha modal do Bootstrap
 */
function fecharModal(idModal) {
    var modalEl = document.getElementById(idModal);
    if (!modalEl) return;
    
    var modal = bootstrap.Modal.getInstance(modalEl);
    if (modal) {
        modal.hide();
    }
}

// ==================== API HELPERS ====================

/**
 * Requisição GET para API
 */
async function apiGet(url) {
    try {
        var response = await fetch(API_BASE + url, {
            headers: {
                'Accept': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error('Erro ' + response.status);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API GET Error:', error);
        mostrarToast('Erro ao carregar dados', 'error');
        throw error;
    }
}

/**
 * Requisição POST para API
 */
async function apiPost(url, data) {
    try {
        var response = await fetch(API_BASE + url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error('Erro ' + response.status);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API POST Error:', error);
        mostrarToast('Erro ao enviar dados', 'error');
        throw error;
    }
}

/**
 * Requisição DELETE para API
 */
async function apiDelete(url) {
    try {
        var response = await fetch(API_BASE + url, {
            method: 'DELETE',
            headers: {
                'Accept': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error('Erro ' + response.status);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API DELETE Error:', error);
        mostrarToast('Erro ao excluir', 'error');
        throw error;
    }
}

// ==================== COPIAR TEXTO ====================

/**
 * Copia texto para área de transferência
 */
function copiarTexto(texto) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texto).then(function() {
            mostrarToast('Copiado para a área de transferência!', 'success', 2000);
        }).catch(function() {
            copiarTextoFallback(texto);
        });
    } else {
        copiarTextoFallback(texto);
    }
}

function copiarTextoFallback(texto) {
    var textarea = document.createElement('textarea');
    textarea.value = texto;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    
    try {
        document.execCommand('copy');
        mostrarToast('Copiado!', 'success', 2000);
    } catch (err) {
        mostrarToast('Erro ao copiar', 'error');
    }
    
    document.body.removeChild(textarea);
}

// ==================== VALIDAÇÃO ====================

/**
 * Valida email
 */
function validarEmail(email) {
    var re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

/**
 * Valida número de matrícula (1-6 dígitos)
 */
function validarMatricula(matricula) {
    var re = /^\d{1,6}$/;
    return re.test(matricula);
}

/**
 * Formata matrícula para 6 dígitos
 */
function formatarMatricula(matricula) {
    return String(matricula).padStart(6, '0');
}

// ==================== ANIMAÇÕES ====================

/**
 * Animação de fade out em elemento
 */
function fadeOut(elemento, duracao, callback) {
    duracao = duracao || 300;
    elemento.style.transition = 'opacity ' + duracao + 'ms ease';
    elemento.style.opacity = '0';
    
    setTimeout(function() {
        if (typeof callback === 'function') {
            callback();
        }
    }, duracao);
}

/**
 * Animação de fade in em elemento
 */
function fadeIn(elemento, duracao) {
    duracao = duracao || 300;
    elemento.style.opacity = '0';
    elemento.style.display = 'block';
    elemento.style.transition = 'opacity ' + duracao + 'ms ease';
    
    setTimeout(function() {
        elemento.style.opacity = '1';
    }, 10);
}

/**
 * Scroll suave até elemento
 */
function scrollPara(elemento) {
    if (typeof elemento === 'string') {
        elemento = document.querySelector(elemento);
    }
    
    if (elemento) {
        elemento.scrollIntoView({ 
            behavior: 'smooth', 
            block: 'start' 
        });
    }
}

// ==================== INICIALIZAÇÃO ====================

document.addEventListener('DOMContentLoaded', function() {
    // Ativar tooltips do Bootstrap
    var tooltipTriggerList = [].slice.call(
        document.querySelectorAll('[data-bs-toggle="tooltip"]')
    );
    
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Ativar popovers do Bootstrap
    var popoverTriggerList = [].slice.call(
        document.querySelectorAll('[data-bs-toggle="popover"]')
    );
    
    popoverTriggerList.map(function(popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Fechar alertas ao clicar no X
    document.querySelectorAll('.alert-custom .btn-close, .alert-premium .btn-close').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var alert = this.closest('.alert-custom, .alert-premium');
            if (alert) {
                fadeOut(alert, 300, function() {
                    alert.remove();
                });
            }
        });
    });
    
    console.log('%c⚽ Pelada FC Admin %cv1.0',
        'font-size: 1.2em; font-weight: bold; color: #10b981;',
        'color: #94a3b8;');
    console.log('%cAdmin JS carregado com sucesso!',
        'color: #64748b; font-style: italic;');
});

// ==================== EXPORT PARA USO GLOBAL ====================
// Tornar funções disponíveis no escopo global
window.PeladaFC = {
    formatarData: formatarData,
    formatarDataHora: formatarDataHora,
    formatarTamanho: formatarTamanho,
    mostrarToast: mostrarToast,
    confirmarAcao: confirmarAcao,
    confirmarAcaoAsync: confirmarAcaoAsync,
    mostrarLoading: mostrarLoading,
    esconderLoading: esconderLoading,
    abrirModal: abrirModal,
    fecharModal: fecharModal,
    apiGet: apiGet,
    apiPost: apiPost,
    apiDelete: apiDelete,
    copiarTexto: copiarTexto,
    validarEmail: validarEmail,
    validarMatricula: validarMatricula,
    formatarMatricula: formatarMatricula,
    fadeOut: fadeOut,
    fadeIn: fadeIn,
    scrollPara: scrollPara
};