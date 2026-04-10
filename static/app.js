document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const modeHelper = document.getElementById('mode-helper');
    const callsignSection = document.getElementById('callsign-section');
    const airportSection = document.getElementById('airport-section');
    const textSection = document.getElementById('text-section');
    const callsignInput = document.getElementById('callsign-input');
    const airportInput = document.getElementById('airport-input');
    const textInput = document.getElementById('text-input');
    const textBtn = document.getElementById('text-btn');
    const textColorPicker = document.getElementById('text-color-picker');
    const updateBtn = document.getElementById('update-btn');
    const airportBtn = document.getElementById('airport-btn');
    const statusMessage = document.getElementById('status-message');
    const flightCard = document.getElementById('flight-card');
    const arrivalsCard = document.getElementById('arrivals-card');
    const fiLogo = document.getElementById('fi-logo');
    const fiModel = document.getElementById('fi-model');
    const fiRoute = document.getElementById('fi-route');
    const fiAlt = document.getElementById('fi-alt');
    const fiSpeed = document.getElementById('fi-speed');
    const fiVs = document.getElementById('fi-vs');
    const fiDistance = document.getElementById('fi-distance');
    const fiNoFlights = document.getElementById('fi-no-flights');
    const fiLastSeen = document.getElementById('fi-last-seen');
    const arrivalsList = document.getElementById('arrivals-list');
    const arrivalsNone = document.getElementById('arrivals-none');
    const arrivalsAirport = document.getElementById('arrivals-airport');

    // Fetch initial state and start polling for live flight data
    fetchState();
    setInterval(fetchState, 10000);

    // Mode Button Events
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const newMode = btn.dataset.mode;
            if (btn.classList.contains('active')) return;

            if (btn.classList.contains('locked')) {
                showStatus('💳 This feature requires a paid FlightAware API key', 'warning');
                return;
            }

            updateUIMode(newMode);
            try {
                await updateServerState({ mode: newMode });
                showStatus(`Switched to ${newMode} mode`, 'success');
            } catch (error) {
                console.error('Failed to update mode:', error);
                showStatus('Failed to connect to tracker', 'error');
            }
        });
    });

    // Callsign Update Event
    updateBtn.addEventListener('click', async () => {
        const callsign = callsignInput.value.trim().toUpperCase();
        if (!callsign) {
            showStatus('Please enter a valid callsign', 'error');
            callsignInput.focus();
            return;
        }
        const originalText = updateBtn.textContent;
        updateBtn.textContent = 'Updating...';
        updateBtn.disabled = true;
        try {
            await updateServerState({ callsign: callsign });
            showStatus(`Now monitoring flight ${callsign}`, 'success');
        } catch (error) {
            console.error('Failed to update callsign:', error);
            showStatus('Failed to update tracker', 'error');
        } finally {
            updateBtn.textContent = originalText;
            updateBtn.disabled = false;
        }
    });

    callsignInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); updateBtn.click(); }
    });
    callsignInput.addEventListener('input', () => {
        const pos = callsignInput.selectionStart;
        callsignInput.value = callsignInput.value.toUpperCase();
        callsignInput.setSelectionRange(pos, pos);
    });

    // Airport Update Event (Arrivals mode)
    airportBtn.addEventListener('click', async () => {
        const airport = airportInput.value.trim().toUpperCase();
        if (!airport) {
            showStatus('Please enter an airport code (e.g. JFK)', 'error');
            airportInput.focus();
            return;
        }
        const originalText = airportBtn.textContent;
        airportBtn.textContent = 'Loading...';
        airportBtn.disabled = true;
        try {
            await updateServerState({ airport: airport, mode: 'arrivals' });
            showStatus(`Showing arrivals for ${airport}`, 'success');
        } catch (error) {
            console.error('Failed to update airport:', error);
            showStatus('Failed to update tracker', 'error');
        } finally {
            airportBtn.textContent = originalText;
            airportBtn.disabled = false;
        }
    });

    airportInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); airportBtn.click(); }
    });
    airportInput.addEventListener('input', () => {
        const pos = airportInput.selectionStart;
        airportInput.value = airportInput.value.toUpperCase();
        airportInput.setSelectionRange(pos, pos);
    });

    // Color Swatch Events
    function getSelectedColor() {
        const activeSwatch = document.querySelector('.color-swatch.active');
        return activeSwatch ? activeSwatch.dataset.color : '#00FF00';
    }

    document.querySelectorAll('.color-swatch').forEach(swatch => {
        swatch.addEventListener('click', (e) => {
            document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
            swatch.classList.add('active');
            // For non-custom swatches, programmatically open the picker if user clicked button itself
            if (swatch.id === 'custom-color-swatch' && e.target !== textColorPicker) {
                textColorPicker.click();
            }
        });
    });

    if (textColorPicker) {
        textColorPicker.addEventListener('input', () => {
            const customSwatch = document.getElementById('custom-color-swatch');
            if (customSwatch) {
                customSwatch.dataset.color = textColorPicker.value;
                customSwatch.style.background = textColorPicker.value;
                document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
                customSwatch.classList.add('active');
            }
        });
    }

    // Text Display Events
    textBtn.addEventListener('click', async () => {
        const text = textInput.value.trim();
        if (!text) {
            showStatus('Please enter some text to display', 'error');
            textInput.focus();
            return;
        }
        const color = getSelectedColor();
        const originalText = textBtn.textContent;
        textBtn.textContent = 'Sending…';
        textBtn.disabled = true;
        try {
            await updateServerState({ text_message: text, text_color: color });
            showStatus(`Displaying on matrix`, 'success');
        } catch (error) {
            console.error('Failed to update text:', error);
            showStatus('Failed to update display', 'error');
        } finally {
            textBtn.textContent = originalText;
            textBtn.disabled = false;
        }
    });

    textInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); textBtn.click(); }
    });

    // Helper Functions
    async function fetchState() {
        try {
            const response = await fetch('/api/state');
            if (!response.ok) throw new Error('Network response was not ok');

            const state = await response.json();

            // Sync mode buttons
            document.querySelectorAll('.mode-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.mode === state.mode);
            });
            updateUIMode(state.mode);

            if (state.callsign) callsignInput.value = state.callsign;
            if (state.airport) airportInput.value = state.airport;
            if (state.text_message) textInput.value = state.text_message;
            if (state.text_color) syncColorSwatch(state.text_color);

            if (state.mode === 'arrivals') {
                updateArrivalsCard(state.current_arrivals, state.airport);
                if (flightCard) flightCard.style.display = 'none';
                if (arrivalsCard) arrivalsCard.style.display = 'block';
            } else if (state.mode === 'text') {
                if (flightCard) flightCard.style.display = 'none';
                if (arrivalsCard) arrivalsCard.style.display = 'none';
            } else {
                updateFlightCard(state.current_flight, state);
                if (flightCard) flightCard.style.display = 'block';
                if (arrivalsCard) arrivalsCard.style.display = 'none';
            }
        } catch (error) {
            console.error('Error fetching state:', error);
            showStatus('Could not connect to Ribs FlightWall', 'error');
        }
    }

    function updateFlightCard(flight, state) {
        if (!flightCard) return;
        flightCard.style.display = 'block';

        if (!flight) {
            fiLogo.style.display = 'none';
            fiLogo.src = '';
            fiModel.textContent = '';
            fiRoute.textContent = '';
            fiAlt.innerHTML = '';
            fiSpeed.innerHTML = '';
            fiVs.textContent = '';
            fiDistance.textContent = '';
            fiVs.className = 'fi-stat fi-vs';

            // Show last-seen flight if available (radius mode)
            const last = state && state.last_seen_flight;
            const lastAt = state && state.last_seen_at;
            if (last && lastAt) {
                const minsAgo = Math.round((Date.now() / 1000 - lastAt) / 60);
                const label = minsAgo < 1 ? 'just now' : `${minsAgo}m ago`;
                fiNoFlights.style.display = 'none';
                fiLastSeen.style.display = 'block';
                fiLastSeen.textContent = `Last seen: ${last.callsign || ''}${last.route ? ' · ' + last.route : ''} — ${label}`;
            } else {
                fiNoFlights.style.display = 'block';
                fiLastSeen.style.display = 'none';
            }
            return;
        }

        fiNoFlights.style.display = 'none';
        fiLastSeen.style.display = 'none';

        if (flight.airline_icao) {
            fiLogo.onload = () => { fiLogo.style.display = 'block'; };
            fiLogo.onerror = () => { fiLogo.style.display = 'none'; };
            fiLogo.style.display = 'none';
            fiLogo.src = `/api/airline-logo/${flight.airline_icao}`;
        } else {
            fiLogo.style.display = 'none';
            fiLogo.src = '';
        }

        fiModel.textContent = flight.aircraft_model || '';
        fiModel.style.display = fiModel.textContent ? 'inline' : 'none';
        fiRoute.textContent = flight.route || '';

        const alt = flight.altitude || 0;
        const altStr = alt >= 1000 ? `${Math.round(alt / 1000)}k` : `${alt}`;
        fiAlt.innerHTML = `Alt <strong>${altStr}</strong>`;

        const spd = flight.speed || 0;
        const spdMph = Math.round(spd * 1.15078);
        fiSpeed.innerHTML = `Spd <strong>${spdMph} mph</strong>`;

        const vs = flight.vertical_speed || 0;
        if (vs > 200) {
            fiVs.textContent = '↑ Climbing';
            fiVs.className = 'fi-stat fi-vs fi-vs-up';
        } else if (vs < -200) {
            fiVs.textContent = '↓ Descending';
            fiVs.className = 'fi-stat fi-vs fi-vs-down';
        } else {
            fiVs.textContent = '';
            fiVs.className = 'fi-stat fi-vs';
        }

        const dist = flight.distance_km;
        fiDistance.textContent = dist != null ? `${dist} km away` : '';
    }

    function updateArrivalsCard(arrivals, airport) {
        if (!arrivalsList || !arrivalsCard) return;
        arrivalsCard.style.display = 'block';

        if (arrivalsAirport) arrivalsAirport.textContent = airport ? `Showing arrivals for ${airport}` : '';

        if (!arrivals || arrivals.length === 0) {
            arrivalsList.innerHTML = '';
            if (arrivalsNone) arrivalsNone.style.display = 'block';
            return;
        }
        if (arrivalsNone) arrivalsNone.style.display = 'none';

        arrivalsList.innerHTML = arrivals.map(a => `
            <div class="arrivals-row">
                <span class="arr-callsign">${a.callsign || '—'}</span>
                <span class="arr-route">${a.route || `${a.origin_iata || '?'} - ${a.dest_iata || '?'}`}</span>
                <span class="arr-eta">${a.eta || '—'}</span>
            </div>
        `).join('');
    }

    async function updateServerState(data) {
        const response = await fetch('/api/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) throw new Error('Server returned an error');
        return await response.json();
    }

    function isModeLocked(mode) {
        const btn = document.querySelector(`.mode-btn[data-mode="${mode}"]`);
        return btn && btn.classList.contains('locked');
    }

    function updateUIMode(mode) {
        if (isModeLocked(mode)) mode = 'radius';
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));

        if (mode === 'monitor') {
            callsignSection.style.display = 'block';
            airportSection.style.display = 'none';
            textSection.style.display = 'none';
            modeHelper.innerHTML = '<strong>Monitor Mode:</strong> Tracks a specific flight globally by its callsign.';
            if (window.innerWidth > 480) setTimeout(() => callsignInput.focus(), 50);
        } else if (mode === 'arrivals') {
            callsignSection.style.display = 'none';
            airportSection.style.display = 'block';
            textSection.style.display = 'none';
            modeHelper.innerHTML = '<strong>Arrivals Mode:</strong> Shows an airport arrivals board on the matrix. Enter an airport code (e.g. JFK).';
            if (window.innerWidth > 480) setTimeout(() => airportInput.focus(), 50);
        } else if (mode === 'text') {
            callsignSection.style.display = 'none';
            airportSection.style.display = 'none';
            textSection.style.display = 'block';
            modeHelper.innerHTML = '<strong>Text Mode:</strong> Display any word or sentence on the matrix. Long text scrolls automatically.';
            if (window.innerWidth > 480) setTimeout(() => textInput.focus(), 50);
        } else if (mode === 'blank') {
            callsignSection.style.display = 'none';
            airportSection.style.display = 'none';
            textSection.style.display = 'none';
            modeHelper.innerHTML = '<strong>Off:</strong> Matrix display is blanked. Switch to another mode to resume.';
        } else {
            callsignSection.style.display = 'none';
            airportSection.style.display = 'none';
            textSection.style.display = 'none';
            modeHelper.innerHTML = '<strong>Radius Mode:</strong> Scans the sky directly above your home for the closest flights.';
        }
    }

    function syncColorSwatch(hexColor) {
        const match = document.querySelector(`.color-swatch:not(#custom-color-swatch)[data-color="${hexColor.toUpperCase()}"]`)
            || document.querySelector(`.color-swatch:not(#custom-color-swatch)[data-color="${hexColor.toLowerCase()}"]`);
        if (match) {
            document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
            match.classList.add('active');
        } else {
            const customSwatch = document.getElementById('custom-color-swatch');
            if (customSwatch) {
                customSwatch.dataset.color = hexColor;
                customSwatch.style.background = hexColor;
                if (textColorPicker) textColorPicker.value = hexColor;
                document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
                customSwatch.classList.add('active');
            }
        }
    }

    let statusTimeout;
    function showStatus(message, type) {
        statusMessage.textContent = message;
        statusMessage.className = `status-message show ${type}`;

        clearTimeout(statusTimeout);
        if (type === 'success') {
            statusTimeout = setTimeout(() => {
                statusMessage.classList.remove('show');
            }, 3000);
        }
        // errors and warnings stay visible until clicked
    }

    statusMessage.addEventListener('click', () => {
        statusMessage.classList.remove('show');
    });

    // Matrix Auto-Refresh logic
    const matrixPreview = document.getElementById('matrix-preview');
    if (matrixPreview) {
        setInterval(() => {
            const currentSrc = new URL(matrixPreview.src, window.location.origin);
            currentSrc.searchParams.set('t', new Date().getTime());
            matrixPreview.src = currentSrc.toString();
        }, 2000); // refresh every 2 seconds
    }

    // Test preset buttons (dev mode only)
    document.querySelectorAll('.btn-test').forEach(btn => {
        btn.addEventListener('click', async () => {
            const preset = btn.dataset.preset;
            document.querySelectorAll('.btn-test').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            await fetch('/debug/test-render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preset }),
            });
        });
    });
});