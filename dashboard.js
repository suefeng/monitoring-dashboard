refreshStatus();
refreshTeam();

function url(port) {
    // set ssl ports here
    const sslPorts = [4200];
    let url = `http://localhost:${port}`;
    if (sslPorts.includes(port)) {
        url = `https://localhost:${port}`;
    }
    return url;
}

async function refreshStatus() {
    const res = await fetch('http://localhost:5055/api/status');
    const data = await res.json();
    if (!data || data.length < 1) {
        return;
    }
    

    document.getElementById('dashboardKnown').innerHTML = data.known.map(s => `
        <tr class="${s.up ? 'up' : 'down'}">
            <td><span class="dot"></span><a href="${url(s.port)}" target="_blank">${s.name}</a></td>
            <td>${s.port}</td>
            <td>${s.up ? 'Running' : 'Not running'}</td>
            <td class="muted">${s.tomcat_webapps ? '<ul class="webapps">' + s.tomcat_webapps.map(w =>
                `<li class="${w.status === 'running' ? 'running' : ''}">${w.webapp} — ${w.status}</li>`
            ).join('') + '</ul>' : '—'}</td>
            <td class="muted">${s.process ? s.process + (s.pid ? ' (pid ' + s.pid + ')' : '') : (s.up ? '—' : '')}</td>
        </tr>
    `).join('');

    document.getElementById('dashboardOther').innerHTML = data.other.map(l => `
        <tr class="up">
            <td>${l.process || 'unknown'}</td>
            <td>${l.port}</td>
            <td class="muted">${l.pid ?? '—'}</td>
        </tr>
    `).join('') || '<tr><td class="muted" colspan="3">Nothing else detected.</td></tr>';
}
