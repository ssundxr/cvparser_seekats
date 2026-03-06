const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const loading = document.getElementById('loading');
const results = document.getElementById('results');
const errorMsg = document.getElementById('error-message');
const parsedDiv = document.getElementById('parsed');
const jsonOutput = document.getElementById('json-output');

const uploadView = document.getElementById('upload-view');
const splitView = document.getElementById('split-view');
const uploadNewBtn = document.getElementById('upload-new-btn');
const pdfContainer = document.getElementById('pdf-container');
const docxContainer = document.getElementById('docx-container');

let currentFile = null;
let currentPdf = null;

// Extracted semantic strings to highlight
let highlightData = {
    personal: [],
    edu: [],
    exp: [],
    skills: []
};

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

uploadNewBtn.addEventListener('click', () => {
    splitView.classList.remove('active');
    setTimeout(() => {
        splitView.classList.add('hidden');
        uploadView.classList.remove('hidden');
        uploadView.classList.add('active');
        fileInput.value = '';
        pdfContainer.innerHTML = '';
        docxContainer.innerHTML = '';
        errorMsg.classList.add('hidden');
    }, 500); // Wait for fade out
});

async function handleFile(file) {
    currentFile = file;
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
    uploadView.classList.remove('active');
    uploadView.classList.add('hidden');
    splitView.classList.remove('hidden');
    splitView.classList.add('active');

    // Show Loading in results area
    parsedDiv.innerHTML = '<div style="display:flex; flex-direction:column; align-items:center; opacity:0.6; padding: 4rem;"> <div class="spinner"></div><p style="margin-top:1rem;">Processing document...</p></div>';
    jsonOutput.textContent = 'Loading...';

    // Begin rendering the document visually on the left side
    renderDocument(file);

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
        applyHighlights(data);

    } catch (err) {
        parsedDiv.innerHTML = `<div class="error" style="margin-top: 2rem;">${err.message}</div>`;
        jsonOutput.textContent = JSON.stringify({ error: err.message }, null, 2);
    }
}

async function renderDocument(file) {
    pdfContainer.innerHTML = '';
    docxContainer.innerHTML = '';

    if (file.name.toLowerCase().endsWith('.pdf')) {
        pdfContainer.classList.remove('hidden');
        docxContainer.classList.add('hidden');

        try {
            const fileReader = new FileReader();
            fileReader.onload = async function () {
                const typedarray = new Uint8Array(this.result);
                currentPdf = await pdfjsLib.getDocument(typedarray).promise;

                for (let pageNum = 1; pageNum <= currentPdf.numPages; pageNum++) {
                    await renderPdfPage(pageNum);
                }
            };
            fileReader.readAsArrayBuffer(file);
        } catch (error) {
            console.error('Error rendering PDF:', error);
            pdfContainer.innerHTML = '<div class="error">Error rendering PDF visually.</div>';
        }
    } else {
        // Fallback for DOCX visual
        pdfContainer.classList.add('hidden');
        docxContainer.classList.remove('hidden');
        docxContainer.innerHTML = '<div style="padding: 2rem; color: #666;">Document uploaded successfully. Parsed data displayed on the right panel.</div>';
    }
}

async function renderPdfPage(pageNum) {
    const page = await currentPdf.getPage(pageNum);

    // Scale the PDF to fit the container width somewhat responsively
    const containerWidth = document.querySelector('.left-pane').clientWidth - 40; // padding minus
    const unscaledViewport = page.getViewport({ scale: 1.0 });
    const scale = containerWidth / unscaledViewport.width;
    const viewport = page.getViewport({ scale: scale > 1.5 ? 1.5 : scale }); // Cap scale

    // Create wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'pdf-page-wrapper';
    wrapper.style.width = `${viewport.width}px`;
    wrapper.style.height = `${viewport.height}px`;

    // Create canvas
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    canvas.height = viewport.height;
    canvas.width = viewport.width;
    wrapper.appendChild(canvas);

    // Create text layer
    const textLayerDiv = document.createElement('div');
    textLayerDiv.className = 'textLayer';
    textLayerDiv.style.width = `${viewport.width}px`;
    textLayerDiv.style.height = `${viewport.height}px`;
    wrapper.appendChild(textLayerDiv);

    pdfContainer.appendChild(wrapper);

    // Render Canvas
    const renderContext = {
        canvasContext: context,
        viewport: viewport
    };
    await page.render(renderContext).promise;

    // Render Text Layer
    const textContent = await page.getTextContent();
    await pdfjsLib.renderTextLayer({
        textContentSource: textContent,
        container: textLayerDiv,
        viewport: viewport,
        textDivs: []
    }).promise;
}

function extractStringsToHighlight(data) {
    highlightData = { personal: [], edu: [], exp: [], skills: [] };

    // Personal
    if (data.name) highlightData.personal.push(data.name);
    if (data.contact_info) {
        if (data.contact_info.email) highlightData.personal.push(data.contact_info.email);
        if (data.contact_info.phone) highlightData.personal.push(data.contact_info.phone);
    }

    // Education
    if (data.education) {
        data.education.forEach(edu => {
            if (edu.institution) highlightData.edu.push(edu.institution);
            if (edu.degree) highlightData.edu.push(edu.degree);
        });
    }

    // Experience
    if (data.experience) {
        data.experience.forEach(exp => {
            if (exp.company) highlightData.exp.push(exp.company);
            if (exp.role) highlightData.exp.push(exp.role);
        });
    }

    // Skills
    if (data.skills) {
        data.skills.forEach(skill => highlightData.skills.push(skill));
    }
}

function applyHighlights(data) {
    extractStringsToHighlight(data);

    // Give the PDF text layer a tiny bit of time to ensure DOM elements are fully painted
    setTimeout(() => {
        const textLayers = document.querySelectorAll('.textLayer');

        textLayers.forEach(layer => {
            const instance = new Mark(layer);

            const markOptions = {
                accuracy: "partially",
                acrossElements: true,
                separateWordSearch: false,
                diacritics: true,
                ignoreJoiners: true
            };

            // Filter function to remove short strings or essentially empty strings
            const filterTerms = (arr) => arr.filter(term => term && term.trim().length > 3);

            // Highlight Education
            filterTerms(highlightData.edu).forEach(term => {
                instance.mark(term, { ...markOptions, className: 'hl-edu' });
            });

            // Highlight Experience
            filterTerms(highlightData.exp).forEach(term => {
                instance.mark(term, { ...markOptions, className: 'hl-exp' });
            });

            // Highlight Personal
            filterTerms(highlightData.personal).forEach(term => {
                instance.mark(term, { ...markOptions, className: 'hl-personal' });
            });

            // Highlight Skills
            filterTerms(highlightData.skills).forEach(term => {
                // Skills usually are single words, maybe 'exactly' is better here but for PDF 'partially' works better with spaces
                instance.mark(term, { ...markOptions, className: 'hl-skills' });
            });
        });
    }, 1000);
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
}
