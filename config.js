// Configuração compartilhada pelas páginas do Kanvira.

// Endereço da API online (Render). Se o Render der outro nome ao serviço, troque aqui.
const API_ONLINE = 'https://kanvira-api.onrender.com/api/v1';
const API_LOCAL = 'http://127.0.0.1:8000/api/v1';

// Abrindo pelo seu PC (localhost ou arquivo) usa a API local; pelo GitHub Pages usa a online.
const rodandoLocal = ['localhost', '127.0.0.1', ''].includes(window.location.hostname);
const API_URL = rodandoLocal ? API_LOCAL : API_ONLINE;

// O Render grátis "dorme" após 15 min sem uso e leva ~1 min para acordar.
// kanviraFetch funciona como fetch, mas avisa o usuário se a resposta demorar.
async function kanviraFetch(url, opcoes) {
    const aviso = setTimeout(mostrarAvisoAcordando, 4000);
    try {
        return await fetch(url, opcoes);
    } finally {
        clearTimeout(aviso);
        esconderAvisoAcordando();
    }
}

function mostrarAvisoAcordando() {
    if (document.getElementById('aviso-acordando')) return;
    const el = document.createElement('div');
    el.id = 'aviso-acordando';
    el.setAttribute('role', 'status');
    el.textContent = '⏳ Acordando o servidor do Kanvira… pode levar até 1 minuto no primeiro acesso.';
    Object.assign(el.style, {
        position: 'fixed', left: '50%', bottom: '24px', transform: 'translateX(-50%)',
        maxWidth: 'calc(100% - 32px)', background: '#161B22', color: '#E6EDF3',
        border: '1px solid #58A6FF', borderRadius: '10px', padding: '12px 18px',
        boxShadow: '0 4px 15px rgba(0,0,0,0.5)', fontSize: '0.92em', zIndex: '50',
        textAlign: 'center',
    });
    document.body.appendChild(el);
}

function esconderAvisoAcordando() {
    document.getElementById('aviso-acordando')?.remove();
}
