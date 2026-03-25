document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const modeHelper = document.getElementById('mode-helper');
    const callsignSection = document.getElementById('callsign-section');
    const airportSection = document.getElementById('airport-section');
    const callsignInput = document.getElementById('callsign-input');
    const airportInput = document.getElementById('airport-input');
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
    const fiNoFlights = document.getElementById('fi-no-flights');
    const arrivalsList = document.getElementById('arrivals-list');
    const arrivalsNone = document.getElementById('arrivals-none');
    const arrivalsAirport = document.getElementById('arrivals-airport');
    const sportsCard = document.getElementById('sports-card');
    const sportsRowAway = document.getElementById('sports-row-away');
    const sportsRowHome = document.getElementById('sports-row-home');
    const sportsStatus = document.getElementById('sports-status');
    const sportsPlaceholder = document.getElementById('sports-placeholder');

    let statePollHandle = null;
    let currentPollMs = -1;

    function setAdaptiveStatePoll(mode) {
        const ms = mode === 'sports' ? 5000 : 10000;
        if (ms === currentPollMs && statePollHandle) return;
        currentPollMs = ms;
        if (statePollHandle) clearInterval(statePollHandle);
        statePollHandle = setInterval(fetchState, ms);
    }

    // Arm polling immediately (10s); first successful fetch may switch to 5s in sports mode
    setAdaptiveStatePoll('radius');
    fetchState();

    // Mode Button Events
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const newMode = btn.dataset.mode;
            if (btn.classList.contains('active')) return;

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

            if (state.mode === 'arrivals') {
                updateArrivalsCard(state.current_arrivals, state.airport);
                if (flightCard) flightCard.style.display = 'none';
                if (arrivalsCard) arrivalsCard.style.display = 'block';
                if (sportsCard) sportsCard.style.display = 'none';
            } else if (state.mode === 'sports') {
                updateSportsCard(state.current_sports);
                if (flightCard) flightCard.style.display = 'none';
                if (arrivalsCard) arrivalsCard.style.display = 'none';
                if (sportsCard) sportsCard.style.display = 'block';
            } else {
                updateFlightCard(state.current_flight);
                if (flightCard) flightCard.style.display = 'block';
                if (arrivalsCard) arrivalsCard.style.display = 'none';
                if (sportsCard) sportsCard.style.display = 'none';
            }

            setAdaptiveStatePoll(state.mode);
        } catch (error) {
            console.error('Error fetching state:', error);
            showStatus('Could not connect to Ribs FlightWall', 'error');
        }
    }

    function updateFlightCard(flight) {
        if (!flightCard) return;
        flightCard.style.display = 'block';

        if (!flight) {
            fiLogo.style.display = 'none';
            fiLogo.src = '';
            fiModel.textContent = '';
            fiRoute.textContent = '';
            fiAlt.innerHTML = '';
            fiSpeed.innerHTML = '';
            fiNoFlights.style.display = 'block';
            return;
        }

        fiNoFlights.style.display = 'none';
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

    function updateSportsCard(sports) {
        if (!sportsCard || !sportsStatus) return;
        sportsCard.style.display = 'block';
        const body = sportsCard.querySelector('.sports-body');

        if (!sports) {
            if (body) body.style.display = 'none';
            if (sportsPlaceholder) sportsPlaceholder.style.display = 'block';
            return;
        }
        if (body) body.style.display = 'block';
        if (sportsPlaceholder) sportsPlaceholder.style.display = 'none';

        const st = sports.status || '';

        const setSingleNyiRow = (message) => {
            if (sportsRowAway) sportsRowAway.style.display = 'none';
            if (sportsRowHome) {
                sportsRowHome.style.display = 'flex';
                sportsRowHome.className = 'sports-row sports-row--nyi';
                sportsRowHome.innerHTML = '<span class="sports-row__team">Islanders</span><span class="sports-row__score">—</span>';
            }
            sportsStatus.textContent = message;
        };

        if (st === 'error') {
            setSingleNyiRow(sports.status_text || 'Score unavailable');
            return;
        }
        if (st === 'no_game') {
            setSingleNyiRow(sports.status_text || 'No game');
            return;
        }

        if (sportsRowAway) sportsRowAway.style.display = 'flex';
        if (sportsRowHome) sportsRowHome.style.display = 'flex';

        const a = sports.away_abbrev || '?';
        const h = sports.home_abbrev || '?';
        const as = sports.away_score != null ? sports.away_score : 0;
        const hs = sports.home_score != null ? sports.home_score : 0;

        sportsRowAway.className = 'sports-row' + (a === 'NYI' ? ' sports-row--nyi' : '');
        sportsRowAway.innerHTML = `<span class="sports-row__team">${a}</span><span class="sports-row__score">${as}</span>`;

        sportsRowHome.className = 'sports-row' + (h === 'NYI' ? ' sports-row--nyi' : '');
        sportsRowHome.innerHTML = `<span class="sports-row__team">${h}</span><span class="sports-row__score">${hs}</span>`;

        sportsStatus.textContent = sports.status_text || '';
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

    function updateUIMode(mode) {
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));

        if (mode === 'monitor') {
            callsignSection.style.display = 'block';
            airportSection.style.display = 'none';
            modeHelper.innerHTML = '<strong>Monitor Mode:</strong> Tracks a specific flight globally by its callsign.';
            if (window.innerWidth > 480) setTimeout(() => callsignInput.focus(), 50);
        } else if (mode === 'arrivals') {
            callsignSection.style.display = 'none';
            airportSection.style.display = 'block';
            modeHelper.innerHTML = '<strong>Arrivals Mode:</strong> Shows an airport arrivals board on the matrix. Enter an airport code (e.g. JFK).';
            if (window.innerWidth > 480) setTimeout(() => airportInput.focus(), 50);
        } else if (mode === 'sports') {
            callsignSection.style.display = 'none';
            airportSection.style.display = 'none';
            modeHelper.innerHTML = '<strong>Sports Mode:</strong> Shows the New York Islanders score on the matrix (NHL). More teams can be added later.';
        } else {
            callsignSection.style.display = 'none';
            airportSection.style.display = 'none';
            modeHelper.innerHTML = '<strong>Radius Mode:</strong> Scans the sky directly above your home for the closest flights.';
        }
    }

    let statusTimeout;
    function showStatus(message, type) {
        statusMessage.textContent = message;
        statusMessage.className = `status-message show ${type}`;
        
        clearTimeout(statusTimeout);
        statusTimeout = setTimeout(() => {
            statusMessage.classList.remove('show');
        }, 3000);
    }

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