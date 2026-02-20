const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const loading = document.getElementById('loading');
const results = document.getElementById('results');
const errorMsg = document.getElementById('error-message');
const parsedDiv = document.getElementById('parsed');
const jsonOutput = document.getElementById('json-output');

// Tabs
document.querySelectorAll('.tab').forEach(button => {
    button.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

        button.classList.add('active');
        document.getElementById(button.dataset.target).classList.add('active');
    });
});

// Drag and drop events
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
        handleFile(e.dataTransfer.files[0]);
    }
});

fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
        handleFile(fileInput.files[0]);
    }
});

async function handleFile(file) {
    // Check if API key is provided
    const apiKeyInput = document.getElementById('api-key-input');
    const apiKey = apiKeyInput ? apiKeyInput.value.trim() : '';

    if (!apiKey) {
        errorMsg.textContent = "Please enter your Gemini API Key before uploading.";
        errorMsg.classList.remove('hidden');
        if (apiKeyInput) apiKeyInput.focus();
        return;
    }

    // Reset UI
    errorMsg.classList.add('hidden');
    results.classList.add('hidden');
    loading.classList.remove('hidden');

    const formData = new FormData();
    formData.append('file', file);
    formData.append('api_key', apiKey);

    try {
        const response = await fetch('/api/parse-cv', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Parsing failed');
        }

        renderResults(data);

    } catch (err) {
        errorMsg.textContent = err.message;
        errorMsg.classList.remove('hidden');
    } finally {
        loading.classList.add('hidden');
        // Clear input to allow re-uploading the same file
        fileInput.value = '';
    }
}

function renderResults(data) {
    // Render Raw JSON
    jsonOutput.textContent = JSON.stringify(data, null, 2);

    // Render Structured Profile
    let html = '';

    // Header (Name & Contact)
    html += `
        <div class="profile-header">
            <h2>${data.name || 'Unknown Candidate'}</h2>
            <div class="contact-row">
    `;
    if (data.contact_info) {
        if (data.contact_info.email) html += `<span>Email: ${data.contact_info.email}</span>`;
        if (data.contact_info.phone) html += `<span>Phone: ${data.contact_info.phone}</span>`;
        if (data.contact_info.linkedin) html += `<span>LinkedIn: ${data.contact_info.linkedin}</span>`;
        if (data.contact_info.github) html += `<span>GitHub: ${data.contact_info.github}</span>`;
    }
    html += `</div></div>`;

    // Experience
    if (data.experience && data.experience.length > 0) {
        html += `<h3 class="section-title">Experience</h3>`;
        data.experience.forEach(exp => {
            html += `
                <div class="item-card">
                    <div class="item-title">${exp.role || ''}</div>
                    <div class="item-subtitle">${exp.company || ''}</div>
                    <div class="item-meta">${exp.start_date || 'N/A'} - ${exp.end_date || 'Present'}</div>
                    <div class="item-desc">${exp.description || ''}</div>
                </div>
            `;
        });
    }

    // Education
    if (data.education && data.education.length > 0) {
        html += `<h3 class="section-title">Education</h3>`;
        data.education.forEach(edu => {
            html += `
                <div class="item-card">
                    <div class="item-title">${edu.institution || ''}</div>
                    <div class="item-subtitle">${edu.degree || ''}</div>
                    <div class="item-meta">Class of ${edu.graduation_year || 'N/A'}</div>
                </div>
            `;
        });
    }

    // Skills
    if (data.skills && data.skills.length > 0) {
        html += `<h3 class="section-title">Skills</h3><div class="skills-list">`;
        data.skills.forEach(skill => {
            html += `<span class="skill-tag">${skill}</span>`;
        });
        html += `</div>`;
    }

    parsedDiv.innerHTML = html;
    results.classList.remove('hidden');
}
