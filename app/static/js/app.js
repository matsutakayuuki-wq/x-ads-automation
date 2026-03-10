async function api(url, method = 'GET', body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body && method !== 'GET') {
        opts.body = JSON.stringify(body);
    }

    const res = await fetch(url, opts);

    if (!res.ok) {
        let errMsg = `Error ${res.status}`;
        try {
            const data = await res.json();
            errMsg = data.detail || errMsg;
        } catch {}
        throw new Error(errMsg);
    }

    const text = await res.text();
    if (!text) return {};
    return JSON.parse(text);
}

function toast(message, type = 'success') {
    window.dispatchEvent(new CustomEvent('show-toast', {
        detail: { message, type }
    }));
}

/**
 * JPY金額をマイクロ通貨に変換
 */
function yenToMicro(yen) {
    return yen * 1000000;
}

/**
 * マイクロ通貨をJPY金額に変換
 */
function microToYen(micro) {
    return Math.floor(micro / 1000000);
}
