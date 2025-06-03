document.addEventListener('DOMContentLoaded', () => {
    const qrInput = document.getElementById('qrInput');
    qrInput.focus(); // Ensure input is focused for scanner

    qrInput.addEventListener('input', async () => {
        const qrData = qrInput.value.trim();
        if (qrData) {
            try {
                const response = await fetch('/parse_qr', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ qrData })
                });
                const data = await response.json();
                if (data.error) {
                    alert('Error: ' + data.error);
                } else {
                    document.getElementById('name').value = data.name || '';
                    document.getElementById('gender').value = data.gender || '';
                    document.getElementById('dob').value = data.dob || '';
                    document.getElementById('address').value = data.address || '';
                    document.getElementById('source').value = data.source || '';
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Failed to decode scanned data.');
            }
            qrInput.value = '';
            qrInput.focus(); // Keep focus for next scan
        }
    });
});
