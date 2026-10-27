// Gemmer felter automatisk og opdaterer beregnede celler uden at genindlæse siden.
// Serveren svarer med HTML; elementer med samme data-k erstattes.

function toast(tekst, fejl) {
  const el = document.getElementById("toast");
  el.textContent = tekst;
  el.className = "toast" + (fejl ? " fejl" : "");
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), fejl ? 6000 : 1500);
}

async function post(url, data) {
  const body = new URLSearchParams(data);
  const svar = await fetch(url, {
    method: "POST",
    headers: { "X-CSRFToken": window.CSRF, "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const tekst = await svar.text();
  if (!svar.ok) throw new Error(svar.status === 400 ? tekst : "Kunne ikke gemme (" + svar.status + ")");
  return tekst;
}

function opdater(html, gemtFelt) {
  const ny = document.createElement("template");
  ny.innerHTML = html;
  ny.content.querySelectorAll("[data-k]").forEach((el) => {
    const gammel = document.querySelector(`[data-k="${CSS.escape(el.dataset.k)}"]`);
    if (!gammel) return;
    if (gammel.matches("input, textarea")) {
      if (gammel !== document.activeElement || gammel === gemtFelt) gammel.value = el.value;
      gammel.defaultValue = el.value;
    } else {
      gammel.replaceWith(el);
    }
  });
}

async function gem(felt, url, data) {
  felt.classList.add("gemmer");
  try {
    opdater(await post(url, data), felt);
    felt.classList.remove("fejl");
    toast("Gemt");
  } catch (e) {
    felt.classList.add("fejl");
    toast(e.message, true);
  } finally {
    felt.classList.remove("gemmer");
  }
}

// Forecast-celler og Pleo-budget
document.addEventListener("change", (ev) => {
  const felt = ev.target;
  if (!felt.matches("input.celle")) return;
  const boks = felt.closest("[data-url]");
  const faelles = { aar: boks.dataset.aar, kvartal: boks.dataset.kvartal, vaerdi: felt.value };
  if (felt.dataset.linje) gem(felt, boks.dataset.url, { ...faelles, linje: felt.dataset.linje, start: felt.dataset.start });
  else if (felt.dataset.afdeling) gem(felt, boks.dataset.url, { ...faelles, afdeling: felt.dataset.afdeling, maaned: felt.dataset.maaned });
});

// Enter går til feltet nedenunder, Escape fortryder.
document.addEventListener("keydown", (ev) => {
  const felt = ev.target;
  if (!felt.matches("input.celle")) return;
  if (ev.key === "Escape") {
    felt.value = felt.defaultValue;
    felt.blur();
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    const celle = felt.closest("td");
    const kol = [...celle.parentElement.children].indexOf(celle);
    let raekke = celle.parentElement.nextElementSibling;
    while (raekke) {
      const naeste = raekke.children[kol]?.querySelector("input.celle");
      if (naeste) return naeste.focus(), naeste.select();
      raekke = raekke.nextElementSibling;
    }
    felt.blur();
  }
});
document.addEventListener("focusin", (ev) => {
  if (ev.target.matches("input.celle")) ev.target.select();
});

// Debitorvurderinger: dato og kommentar gemmes, når feltet forlades.
document.addEventListener("change", (ev) => {
  const felt = ev.target;
  const raekke = felt.closest("tr.deb-raekke");
  if (!raekke) return;
  const data = {};
  raekke.querySelectorAll("[name]").forEach((f) => (data[f.name] = f.value));
  gem(felt, raekke.dataset.url, data).then(() => {
    // Rækkens farve følger status.
    const status = raekke.querySelector(".status");
    raekke.classList.toggle("ikke-forventet", !!status?.querySelector(".roed"));
    raekke.classList.toggle("forfalden", !status?.querySelector(".roed") && !!status?.querySelector(".orange"));
  });
});

// Graf over forventet saldo
function tegnSaldograf(id, data) {
  const css = getComputedStyle(document.documentElement);
  const farver = [css.getPropertyValue("--serie-1").trim(), css.getPropertyValue("--serie-2").trim()];
  const kr = new Intl.NumberFormat("da-DK", { maximumFractionDigits: 0 });
  const datasets = [];
  data.serier.forEach((s, i) => {
    datasets.push({ label: s.navn, data: s.saldi, borderColor: farver[i], backgroundColor: farver[i], tension: 0.25, pointRadius: 3, borderWidth: 2 });
    datasets.push({ label: `Minimum ${s.navn}`, data: data.labels.map(() => s.minimum), borderColor: farver[i], borderDash: [5, 4], borderWidth: 1, pointRadius: 0 });
  });
  new Chart(document.getElementById(id), {
    type: "line",
    data: { labels: data.labels, datasets },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { filter: (item) => !item.text.startsWith("Minimum"), usePointStyle: true, boxHeight: 6 } },
        tooltip: { filter: (item) => !item.dataset.label.startsWith("Minimum"), callbacks: { label: (c) => `${c.dataset.label}: ${kr.format(c.parsed.y)} kr.` } },
      },
      scales: {
        y: { ticks: { callback: (v) => kr.format(v) }, grid: { color: css.getPropertyValue("--linje").trim() } },
        x: { grid: { display: false } },
      },
    },
  });
}
