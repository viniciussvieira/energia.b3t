// Campo de busca de time com escudo, usado em "Novo bolão" e "Editar bolão".
// Uso:
//   container.innerHTML = BuscaTime.html({ id: 'time_a', placeholder: '...', nome: 'Flamengo', escudo: url });
//   const campo = BuscaTime.ativar(container.querySelector('.busca-wrap'), { api, aoMudar });
//   campo.nome / campo.escudo / campo.limpar()
// Precisa de uma função api(rota) que devolve { ok, dados } (cada página já tem a sua).

const BuscaTime = (() => {
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const ICONE_VAZIO = '<i class="fas fa-shield-halved"></i>';

    const CSS = `
        .busca-wrap { position: relative; }
        .busca-wrap input { padding-left: 52px !important; }
        .busca-wrap .escudo-preview {
            position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
            width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
            color: var(--text-muted); pointer-events: none;
        }
        .busca-wrap .escudo-preview img { max-width: 32px; max-height: 32px; object-fit: contain; }
        .busca-wrap .sugestoes {
            position: absolute; top: calc(100% + 6px); left: 0; right: 0; list-style: none;
            background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5); max-height: 300px; overflow-y: auto; z-index: 20; padding: 4px;
        }
        .busca-wrap .sugestoes li {
            display: flex; align-items: center; gap: 12px; padding: 8px 10px; border-radius: 8px; cursor: pointer; text-align: left;
        }
        .busca-wrap .sugestoes li.ativo, .busca-wrap .sugestoes li:hover { background: rgba(88, 166, 255, 0.12); }
        .busca-wrap .sugestoes li img, .busca-wrap .sugestoes li .sem-escudo {
            width: 32px; height: 32px; object-fit: contain; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center; color: var(--text-muted);
        }
        .busca-wrap .sugestoes li span { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
        .busca-wrap .sugestoes li small { color: var(--text-muted); font-size: 0.8em; }
        .busca-wrap .sugestoes li.info { cursor: default; color: var(--text-muted); font-size: 0.88em; }
        .busca-wrap .sugestoes li.info:hover { background: transparent; }
        .busca-wrap .tirar-escudo {
            position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
            background: transparent; border: none; color: var(--text-muted); cursor: pointer;
            font-size: 0.8em; padding: 4px 6px; border-radius: 6px;
        }
        .busca-wrap .tirar-escudo:hover { color: var(--error); }
    `;

    function injetarCSS() {
        if (document.getElementById('css-busca-times')) return;
        const style = document.createElement('style');
        style.id = 'css-busca-times';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function html({ id, placeholder = 'Digite para buscar o time', nome = '', escudo = null, rotulo = '' }) {
        return `<div class="busca-wrap" data-escudo="${esc(escudo || '')}">
            <span class="escudo-preview" aria-hidden="true">${escudo ? `<img src="${esc(escudo)}" alt="">` : ICONE_VAZIO}</span>
            <input type="text" id="${esc(id)}" value="${esc(nome)}" required minlength="2" maxlength="50"
                   placeholder="${esc(placeholder)}" autocomplete="off" role="combobox" aria-autocomplete="list"
                   aria-expanded="false" aria-controls="sug-${esc(id)}" ${rotulo ? `aria-label="${esc(rotulo)}"` : ''}>
            <button type="button" class="tirar-escudo" title="Tirar o escudo" aria-label="Tirar o escudo" ${escudo ? '' : 'hidden'}>✕</button>
            <ul class="sugestoes" id="sug-${esc(id)}" role="listbox" hidden></ul>
        </div>`;
    }

    function ativar(wrap, { api, aoMudar = () => {} }) {
        injetarCSS();
        const input = wrap.querySelector('input');
        const lista = wrap.querySelector('.sugestoes');
        const preview = wrap.querySelector('.escudo-preview');
        const tirar = wrap.querySelector('.tirar-escudo');
        let escudo = wrap.dataset.escudo || null;
        let resultados = [], ativo = -1, timer = null, ultimaBusca = 0;

        function definirEscudo(url) {
            escudo = url || null;
            preview.innerHTML = escudo ? `<img src="${esc(escudo)}" alt="">` : ICONE_VAZIO;
            tirar.hidden = !escudo;
            aoMudar();
        }

        const fechar = () => { lista.hidden = true; input.setAttribute('aria-expanded', 'false'); ativo = -1; };
        const abrir = () => { lista.hidden = false; input.setAttribute('aria-expanded', 'true'); };

        function marcarAtivo(i) {
            ativo = i;
            lista.querySelectorAll('li[data-i]').forEach(li => {
                const sel = +li.dataset.i === i;
                li.classList.toggle('ativo', sel);
                li.setAttribute('aria-selected', sel);
                if (sel) li.scrollIntoView({ block: 'nearest' });
            });
        }

        function escolher(i) {
            const t = resultados[i];
            if (!t) return;
            input.value = t.nome;
            definirEscudo(t.escudo);
            fechar();
        }

        function mostrar(times, termo) {
            resultados = times;
            lista.innerHTML = times.length
                ? times.map((t, i) => `
                    <li role="option" data-i="${i}" aria-selected="false">
                        ${t.escudo ? `<img src="${esc(t.escudo)}" alt="" loading="lazy">` : '<i class="fas fa-shield-halved sem-escudo"></i>'}
                        <span>${esc(t.nome)}<small>${esc(t.liga)}</small></span>
                    </li>`).join('')
                : `<li class="info">Nenhum time encontrado para "${esc(termo)}". Pode seguir com o nome digitado.</li>`;
            abrir();
            marcarAtivo(times.length ? 0 : -1);
        }

        input.addEventListener('input', () => {
            definirEscudo(null);  // mudou o nome: o escudo escolhido antes não vale mais
            clearTimeout(timer);
            const termo = input.value.trim();
            if (termo.length < 2) return fechar();
            timer = setTimeout(async () => {
                const id = ++ultimaBusca;
                lista.innerHTML = '<li class="info">Buscando...</li>';
                abrir();
                try {
                    const { ok, dados } = await api(`/times/busca?q=${encodeURIComponent(termo)}`);
                    if (id === ultimaBusca) mostrar(ok ? dados : [], termo);
                } catch (err) {
                    if (id === ultimaBusca) lista.innerHTML = '<li class="info">Não foi possível buscar agora. Pode digitar o nome.</li>';
                }
            }, 300);
        });

        input.addEventListener('keydown', e => {
            if (lista.hidden || !resultados.length) return;
            if (e.key === 'ArrowDown') { e.preventDefault(); marcarAtivo(Math.min(ativo + 1, resultados.length - 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); marcarAtivo(Math.max(ativo - 1, 0)); }
            else if (e.key === 'Enter' && ativo >= 0) { e.preventDefault(); escolher(ativo); }
            else if (e.key === 'Escape') fechar();
        });

        // mousedown (e não click) para escolher antes do input perder o foco
        lista.addEventListener('mousedown', e => {
            const li = e.target.closest('li[data-i]');
            if (li) { e.preventDefault(); escolher(+li.dataset.i); }
        });
        input.addEventListener('blur', () => setTimeout(fechar, 120));
        tirar.addEventListener('click', () => { definirEscudo(null); input.focus(); });

        return {
            get nome() { return input.value.trim(); },
            get escudo() { return escudo; },
            limpar() { input.value = ''; definirEscudo(null); },
        };
    }

    return { html, ativar };
})();
