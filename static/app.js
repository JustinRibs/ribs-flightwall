document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const modeToggle = document.getElementById('mode-toggle');
    const labelRadius = document.getElementById('label-radius');
    const labelMonitor = document.getElementById('label-monitor');
    const modeHelper = document.getElementById('mode-helper');
    const callsignSection = document.getElementById('callsign-section');
    const callsignInput = document.getElementById('callsign-input');
    const updateBtn = document.getElementById('update-btn');
    const statusMessage = document.getElementById('status-message');
    const flightCard = document.getElementById('flight-card');
    const fiLogo = document.getElementById('fi-logo');
    const fiCallsign = document.getElementById('fi-callsign');
    const fiModel = document.getElementById('fi-model');
    const fiRoute = document.getElementById('fi-route');
    const fiAlt = document.getElementById('fi-alt');
    const fiSpeed = document.getElementById('fi-speed');
    const fiNoFlights = document.getElementById('fi-no-flights');

    // Fetch initial state and start polling for live flight data
    fetchState();
    setInterval(fetchState, 10000);

    // Mode Toggle Event
    modeToggle.addEventListener('change', async (e) => {
        const isMonitor = e.target.checked;
        const newMode = isMonitor ? 'monitor' : 'radius';
        
        updateUIMode(newMode);
        
        try {
            await updateServerState({ mode: newMode });
            showStatus(`Switched to ${newMode} mode`, 'success');
        } catch (error) {
            console.error('Failed to update mode:', error);
            showStatus('Failed to connect to tracker', 'error');
            // Revert UI on failure
            modeToggle.checked = !isMonitor;
            updateUIMode(!isMonitor ? 'monitor' : 'radius');
        }
    });

    // Callsign Update Event
    updateBtn.addEventListener('click', async () => {
        const callsign = callsignInput.value.trim().toUpperCase();
        
        if (!callsign) {
            showStatus('Please enter a valid callsign', 'error');
            callsignInput.focus();
            return;
        }

        // Add loading state to button
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
            // Restore button
            updateBtn.textContent = originalText;
            updateBtn.disabled = false;
        }
    });

    // Allow Enter key to trigger update
    callsignInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            updateBtn.click();
        }
    });

    // Force uppercase as the user types (CSS handles visual, this ensures .value is also uppercase)
    callsignInput.addEventListener('input', () => {
        const pos = callsignInput.selectionStart;
        callsignInput.value = callsignInput.value.toUpperCase();
        callsignInput.setSelectionRange(pos, pos);
    });

    // Helper Functions
    async function fetchState() {
        try {
            const response = await fetch('/api/state');
            if (!response.ok) throw new Error('Network response was not ok');

            const state = await response.json();

            // Sync UI with server state
            if (state.mode === 'monitor') {
                modeToggle.checked = true;
                updateUIMode('monitor');
            } else {
                modeToggle.checked = false;
                updateUIMode('radius');
            }

            if (state.callsign) {
                callsignInput.value = state.callsign;
            }

            updateFlightCard(state.current_flight);
        } catch (error) {
            console.error('Error fetching initial state:', error);
            showStatus('Could not connect to Ribs FlightWall', 'error');
        }
    }

    function updateFlightCard(flight) {
        if (!flightCard) return;

        flightCard.style.display = 'block';

        if (!flight) {
            fiLogo.style.display = 'none';
            fiLogo.src = '';
            fiCallsign.textContent = '';
            fiModel.textContent = '';
            fiRoute.textContent = '';
            fiAlt.innerHTML = '';
            fiSpeed.innerHTML = '';
            fiNoFlights.style.display = 'block';
            return;
        }

        fiNoFlights.style.display = 'none';

        // Airline logo via logo.dev proxy
        if (flight.airline_icao) {
            fiLogo.onload = () => { fiLogo.style.display = 'block'; };
            fiLogo.onerror = () => { fiLogo.style.display = 'none'; };
            fiLogo.style.display = 'none';
            fiLogo.src = `/api/airline-logo/${flight.airline_icao}`;
        } else {
            fiLogo.style.display = 'none';
            fiLogo.src = '';
        }

        fiCallsign.textContent = flight.callsign || '—';

        const model = flight.aircraft_model || '';
        fiModel.textContent = model;
        fiModel.style.display = model ? 'inline' : 'none';

        fiRoute.textContent = flight.route || '';

        const alt = flight.altitude || 0;
        const altStr = alt >= 1000 ? `${Math.round(alt / 1000)}k ft` : `${alt} ft`;
        fiAlt.innerHTML = `Height: <strong>${altStr}</strong>`;

        const spd = flight.speed || 0;
        fiSpeed.innerHTML = `Speed: <strong>${spd} kt</strong>`;
    }

    async function updateServerState(data) {
        const response = await fetch('/api/state', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error('Server returned an error');
        }
        
        return await response.json();
    }

    function updateUIMode(mode) {
        if (mode === 'monitor') {
            labelMonitor.classList.add('active');
            labelRadius.classList.remove('active');
            callsignSection.style.display = 'block';
            modeHelper.innerHTML = '<strong>Monitor Mode:</strong> Tracks a specific flight globally by its callsign.';
            
            // Slight delay before focusing to allow animation/display
            setTimeout(() => {
                if(window.innerWidth > 480) { // Don't auto-focus on mobile to prevent keyboard popup
                    callsignInput.focus();
                }
            }, 50);
        } else {
            labelRadius.classList.add('active');
            labelMonitor.classList.remove('active');
            callsignSection.style.display = 'none';
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