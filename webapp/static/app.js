/* Portal de Cartas de Cobrança · comportamento das telas (sem dependências) */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // ---------- tema claro/escuro ----------
  var btnTema = $("#alternar-tema");
  if (btnTema) {
    btnTema.addEventListener("click", function () {
      var raiz = document.documentElement;
      var escuroAgora = raiz.dataset.tema === "escuro" ||
        (!raiz.dataset.tema && window.matchMedia("(prefers-color-scheme: dark)").matches);
      var novo = escuroAgora ? "claro" : "escuro";
      raiz.dataset.tema = novo;
      try { localStorage.setItem("tema", novo); } catch (e) {}
    });
  }

  // ---------- confirmação em formulários destrutivos ----------
  $$("form[data-confirmar]").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (!window.confirm(f.dataset.confirmar)) ev.preventDefault();
    });
  });

  // ---------- envio de planilha ----------
  var inputArq = $("#planilha"), zona = $("#zona-arquivo"), nome = $("#zona-nome"), btnGerar = $("#btn-gerar");
  if (inputArq) {
    var mostrar = function () {
      var f = inputArq.files && inputArq.files[0];
      nome.hidden = !f;
      nome.textContent = f ? f.name + " (" + (f.size / 1024 / 1024).toFixed(2) + " MB)" : "";
      btnGerar.disabled = !f;
    };
    inputArq.addEventListener("change", mostrar);
    ["dragenter", "dragover"].forEach(function (t) {
      zona.addEventListener(t, function (e) { e.preventDefault(); zona.classList.add("arrastando"); });
    });
    ["dragleave", "drop"].forEach(function (t) {
      zona.addEventListener(t, function (e) { e.preventDefault(); zona.classList.remove("arrastando"); });
    });
    zona.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) { inputArq.files = e.dataTransfer.files; mostrar(); }
    });
    $("#form-envio").addEventListener("submit", function () {
      btnGerar.disabled = true;
      btnGerar.textContent = "Enviando…";
    });
  }

  // ---------- acompanhamento da geração ----------
  var painel = $("#painel-status");
  if (painel) {
    var url = painel.dataset.statusUrl;
    var checar = function () {
      fetch(url, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.status !== "processando") window.location.reload();
          else setTimeout(checar, 2000);
        })
        .catch(function () { setTimeout(checar, 5000); });
    };
    setTimeout(checar, 2000);
  }

  // ---------- filtro e seleção de beneficiários ----------
  var filtro = $("#filtro"), tabela = $("#tabela-cartas");
  if (filtro && tabela) {
    var linhas = $$("tbody tr", tabela);
    var contVisivel = $("#contagem-visivel"), vazio = $("#vazio-filtro");
    var marcarTodos = $("#marcar-todos"), btnSel = $("#btn-baixar-sel"), qtdSel = $("#qtd-sel");

    var normalizar = function (s) {
      return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    };
    var atualizarSelecao = function () {
      var n = $$(".chk:checked", tabela).length;
      if (qtdSel) qtdSel.textContent = n;
      if (btnSel) btnSel.disabled = n === 0;
      if (marcarTodos) {
        var visiveis = linhas.filter(function (tr) { return !tr.classList.contains("oculta"); });
        var marcadosVisiveis = visiveis.filter(function (tr) { var c = $(".chk", tr); return c && c.checked; }).length;
        marcarTodos.checked = visiveis.length > 0 && marcadosVisiveis === visiveis.length;
        marcarTodos.indeterminate = marcadosVisiveis > 0 && marcadosVisiveis < visiveis.length;
      }
    };
    var aplicarFiltro = function () {
      var termos = normalizar(filtro.value).split(/\s+/).filter(Boolean);
      var visiveis = 0;
      linhas.forEach(function (tr) {
        var alvo = normalizar(tr.dataset.busca || "");
        var ok = termos.every(function (t) { return alvo.indexOf(t) !== -1; });
        tr.classList.toggle("oculta", !ok);
        if (ok) visiveis++;
      });
      contVisivel.textContent = visiveis;
      vazio.hidden = visiveis > 0;
      atualizarSelecao();
    };
    filtro.addEventListener("input", aplicarFiltro);
    filtro.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { filtro.value = ""; aplicarFiltro(); }
      if (e.key === "Enter") e.preventDefault();  // Enter no filtro não dispara o download
    });
    tabela.addEventListener("change", function (e) {
      if (e.target.classList.contains("chk")) atualizarSelecao();
    });
    if (marcarTodos) {
      marcarTodos.addEventListener("change", function () {
        linhas.forEach(function (tr) {
          if (tr.classList.contains("oculta")) return;
          var c = $(".chk", tr); if (c) c.checked = marcarTodos.checked;
        });
        atualizarSelecao();
      });
    }
    // "/" foca o filtro (atalho de teclado)
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== filtro && !/input|textarea|select/i.test(document.activeElement.tagName)) {
        e.preventDefault(); filtro.focus();
      }
    });
    atualizarSelecao();
  }
})();
