/**
 * ==============================================================================
 * Canva / MS Word Grade Visual PDF Resume Editor — Core JavaScript Engine
 * ==============================================================================
 * Features:
 * 1. 100% Direct Editable (Single-click cursor placement everywhere, no dblclick required)
 * 2. Word-Level Text Formatting & Selection-Aware Font Sizing
 *    - Highlight text & click +/- => scales ONLY the selected text!
 *    - Click inside an element (heading, title, name, bullet) => scales THAT element!
 *    - Toolbar mousedown prevents focus loss so selection is never dropped!
 *    - Dynamic selectionchange listener syncs toolbar font size/family with cursor.
 * 3. Word-Grade Bullet Handling:
 *    - Press Enter in a bullet => inserts a new bullet point below, places caret in it.
 *    - Press Backspace on empty bullet => deletes bullet, merges back.
 *    - Press Shift+Enter => inserts soft break (<br>) for manual spacing.
 * 4. Total De-Congestion & Spacing Controls:
 *    - Active "Space After" (margin-bottom) slider and number input in Inspector.
 *    - Quick "+4px Space" and "-4px Space" buttons on every section and in Inspector.
 *    - Bullet gap and line height sliders.
 * 5. Independent Section Reordering & Drag & Drop:
 *    - Dedicated ▲ Move Up and ▼ Move Down buttons on every section.
 *    - Reliable Drag & Drop handle with visual insertion guide line.
 * 6. Embedded Gemini 2.5 AI Polish Studio:
 *    - Top toolbar AI Polish button, floating text toolbar AI button, block hover AI button.
 *    - 5 Quick 1-click enhancements: Metrics, Verbs, ATS Keywords, Concise, Executive Tone.
 *    - Custom instruction prompt + Before/After diff card with 1-click Apply.
 * 7. 1:1 Pixel-Perfect PDF Vector Export:
 *    - Passes exact client DOM to Playwright for 100% fidelity with the screen.
 *    - 2-3s fast headless render + 0s Instant Print to PDF option.
 * ==============================================================================
 */

(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════
  // 1. STATE STORE (Snapshots, CSS Variables, Reactive Listeners)
  // ═══════════════════════════════════════════════════════════════════

  class EditorStore {
    constructor() {
      this.state = {
        resume: {},
        styles: {
          page: {
            size: 'Letter',
            marginTop: '0.35in',
            marginBottom: '0.35in',
            marginLeft: '0.45in',
            marginRight: '0.45in'
          },
          typography: {
            fontFamily: 'Carlito',
            fontSize: '9.5pt',
            lineHeight: '1.22',
            letterSpacing: '0px'
          },
          spacing: {
            sectionGap: '6px',
            entryGap: '4px',
            bulletGap: '1px'
          },
          colors: {
            text: '#000000',
            accent: '#111827',
            border: '#111827',
            link: '#1a56db'
          },
          sectionOrder: ['summary', 'skills', 'experience', 'education', 'certifications', 'projects']
        },
        selectedBlockId: null,
        zoom: 100,
        isDirty: false
      };

      this.history = [];
      this.historyIndex = -1;
      this.maxHistory = 50;
      this.listeners = [];
    }

    init(initialResume) {
      if (initialResume && typeof initialResume === 'object') {
        this.state.resume = JSON.parse(JSON.stringify(initialResume));
        if (initialResume.editor_styles && typeof initialResume.editor_styles === 'object') {
          this.state.styles = this._mergeStyles(this.state.styles, initialResume.editor_styles);
        }
      }
      this.applyStylesToArtboard();
      this.pushSnapshot('Initial Load');
      this.state.isDirty = false;
    }

    _mergeStyles(base, incoming) {
      const merged = JSON.parse(JSON.stringify(base));
      for (const cat in incoming) {
        if (merged[cat] && typeof incoming[cat] === 'object' && !Array.isArray(incoming[cat])) {
          Object.assign(merged[cat], incoming[cat]);
        } else {
          merged[cat] = incoming[cat];
        }
      }
      return merged;
    }

    subscribe(fn) {
      this.listeners.push(fn);
    }

    notify(changeType, payload) {
      for (const fn of this.listeners) {
        try {
          fn(changeType, payload, this.state);
        } catch (err) {
          console.error('[EditorStore] Listener error:', err);
        }
      }
    }

    pushSnapshot(label = 'Action') {
      if (this.historyIndex < this.history.length - 1) {
        this.history = this.history.slice(0, this.historyIndex + 1);
      }

      const snapshot = {
        label,
        resume: JSON.parse(JSON.stringify(this.state.resume)),
        styles: JSON.parse(JSON.stringify(this.state.styles)),
        domHtml: document.getElementById('resumeContent') ? document.getElementById('resumeContent').innerHTML : '',
        timestamp: Date.now()
      };

      this.history.push(snapshot);
      if (this.history.length > this.maxHistory) {
        this.history.shift();
      } else {
        this.historyIndex++;
      }

      this.state.isDirty = true;
      this.notify('history_change', { canUndo: this.canUndo(), canRedo: this.canRedo() });
    }

    canUndo() {
      return this.historyIndex > 0;
    }

    canRedo() {
      return this.historyIndex < this.history.length - 1;
    }

    undo() {
      if (!this.canUndo()) return;
      this.historyIndex--;
      const snapshot = this.history[this.historyIndex];
      this.state.resume = JSON.parse(JSON.stringify(snapshot.resume));
      this.state.styles = JSON.parse(JSON.stringify(snapshot.styles));
      this.applyStylesToArtboard();
      if (snapshot.domHtml && document.getElementById('resumeContent')) {
        document.getElementById('resumeContent').innerHTML = snapshot.domHtml;
        InlineEditor.attachAllListeners();
      } else {
        BlockRenderer.renderAll(this.state.resume, this.state.styles);
      }
      this.notify('undo_applied', snapshot);
    }

    redo() {
      if (!this.canRedo()) return;
      this.historyIndex++;
      const snapshot = this.history[this.historyIndex];
      this.state.resume = JSON.parse(JSON.stringify(snapshot.resume));
      this.state.styles = JSON.parse(JSON.stringify(snapshot.styles));
      this.applyStylesToArtboard();
      if (snapshot.domHtml && document.getElementById('resumeContent')) {
        document.getElementById('resumeContent').innerHTML = snapshot.domHtml;
        InlineEditor.attachAllListeners();
      } else {
        BlockRenderer.renderAll(this.state.resume, this.state.styles);
      }
      this.notify('redo_applied', snapshot);
    }

    updateStyle(category, key, value) {
      if (!this.state.styles[category]) {
        this.state.styles[category] = {};
      }
      this.state.styles[category][key] = value;
      this.applyStylesToArtboard();
      this.pushSnapshot(`Update ${category}.${key}`);
      this.notify('style_updated', { category, key, value });
      AutoSaver.trigger();
    }

    applyStylesToArtboard() {
      const artboard = document.getElementById('editorArtboard');
      if (!artboard) return;

      const { typography, spacing, colors, page } = this.state.styles;

      const font = typography.fontFamily || 'Carlito';
      artboard.style.setProperty('--resume-font', `'${font}', 'Calibri', 'Segoe UI', Arial, sans-serif`);
      artboard.style.setProperty('--resume-base-size', typography.fontSize || '9.5pt');
      artboard.style.setProperty('--resume-line-height', typography.lineHeight || '1.22');
      artboard.style.setProperty('--resume-letter-spacing', typography.letterSpacing || '0px');

      artboard.style.setProperty('--resume-section-gap', spacing.sectionGap || '6px');
      artboard.style.setProperty('--resume-entry-gap', spacing.entryGap || '4px');
      artboard.style.setProperty('--resume-bullet-gap', spacing.bulletGap || '1px');

      artboard.style.setProperty('--resume-text-color', colors.text || '#000000');
      artboard.style.setProperty('--resume-border-color', colors.border || '#111827');
      artboard.style.setProperty('--resume-link-color', colors.link || '#1a56db');

      if (page) {
        artboard.style.setProperty('--paper-margin-t', page.marginTop || '0.35in');
        artboard.style.setProperty('--paper-margin-b', page.marginBottom || '0.35in');
        artboard.style.setProperty('--paper-margin-l', page.marginLeft || '0.45in');
        artboard.style.setProperty('--paper-margin-r', page.marginRight || '0.45in');
      }
    }

    selectBlock(blockId) {
      this.state.selectedBlockId = blockId;
      this.notify('block_selected', { blockId });
    }

    clearSelection() {
      this.state.selectedBlockId = null;
      this.notify('selection_cleared', {});
    }
  }

  const store = new EditorStore();
  window.editorStore = store;


  // ═══════════════════════════════════════════════════════════════════
  // 2. BLOCK RENDERER (100% Direct Editable, Block Action Controls)
  // ═══════════════════════════════════════════════════════════════════

  class BlockRenderer {
    static escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    static renderAll(resume, styles) {
      const container = document.getElementById('resumeContent');
      if (!container) return;
      container.innerHTML = '';

      // 1. Header Block
      container.appendChild(BlockRenderer.renderHeader(resume));

      // 2. Sections in designated order
      const order = styles.sectionOrder || ['summary', 'skills', 'experience', 'education', 'certifications', 'projects'];
      for (const secKey of order) {
        const el = BlockRenderer.renderSection(secKey, resume);
        if (el) container.appendChild(el);
      }

      // Re-apply block selection if active
      if (store.state.selectedBlockId) {
        const sel = container.querySelector(`[data-block-id="${store.state.selectedBlockId}"]`);
        if (sel) sel.classList.add('selected');
      }

      // Attach all event listeners to new contenteditable elements
      InlineEditor.attachAllListeners();

      // Check overflow
      setTimeout(() => PageOverflowDetector.check(), 60);
    }

    static createBlockWrapper(blockId, blockType) {
      const wrapper = document.createElement('div');
      wrapper.className = 'editor-block';
      wrapper.setAttribute('data-block-id', blockId);
      wrapper.setAttribute('data-block-type', blockType);

      // 1. Static Drag Handle on left
      const handle = document.createElement('div');
      handle.className = 'block-drag-handle';
      handle.setAttribute('draggable', 'true');
      handle.title = 'Drag to reorder section';
      handle.innerHTML = '<i class="fa-solid fa-grip-vertical"></i>';
      wrapper.appendChild(handle);

      // 2. Hover Actions Bar on top-right (Move Up, Move Down, Space, AI, Delete)
      const actionsBar = document.createElement('div');
      actionsBar.className = 'block-actions-bar';

      let actionsHtml = `
        <button class="block-action-btn btn-move-up" title="Move Up (▲)"><i class="fa-solid fa-arrow-up"></i></button>
        <button class="block-action-btn btn-move-down" title="Move Down (▼)"><i class="fa-solid fa-arrow-down"></i></button>
        <button class="block-action-btn btn-add-space" title="Add 4px space below"><i class="fa-solid fa-arrows-up-down"></i> +Space</button>
      `;

      if (['experience-entry', 'education', 'certifications', 'projects'].includes(blockType)) {
        actionsHtml += `<button class="block-action-btn btn-add-bullet" title="Add new bullet point"><i class="fa-solid fa-plus"></i> Bullet</button>`;
      }

      actionsHtml += `
        <button class="block-action-btn ai-btn btn-ai-polish" title="Polish with Gemini AI"><i class="fa-solid fa-wand-magic-sparkles"></i> AI</button>
        <button class="block-action-btn danger-btn btn-delete-block" title="Delete section"><i class="fa-solid fa-trash"></i></button>
      `;

      actionsBar.innerHTML = actionsHtml;
      wrapper.appendChild(actionsBar);

      return wrapper;
    }

    static renderHeader(resume) {
      const block = BlockRenderer.createBlockWrapper('header', 'header');

      const headerDiv = document.createElement('div');
      headerDiv.className = 'resume-header';

      const name = resume.name || 'CANDIDATE NAME';
      const role = resume.target_role || '';
      const contact = resume.contact || {};

      let html = `<div class="candidate-name" contenteditable="true" data-edit="name">${BlockRenderer.escapeHtml(name.toUpperCase())}</div>`;
      if (role || role === '') {
        html += `<div class="target-role" contenteditable="true" data-edit="target_role">${BlockRenderer.escapeHtml(role || 'Target Role / Professional Title')}</div>`;
      }

      const parts = [];
      if (contact.email) parts.push(`<a href="mailto:${BlockRenderer.escapeHtml(contact.email)}" contenteditable="true" data-edit="contact-email">${BlockRenderer.escapeHtml(contact.email)}</a>`);
      if (contact.phone) parts.push(`<a href="tel:${BlockRenderer.escapeHtml(contact.phone)}" contenteditable="true" data-edit="contact-phone">${BlockRenderer.escapeHtml(contact.phone)}</a>`);
      if (contact.location) parts.push(`<span contenteditable="true" data-edit="contact-location">${BlockRenderer.escapeHtml(contact.location)}</span>`);
      if (contact.linkedin) {
        const url = contact.linkedin.startsWith('http') ? contact.linkedin : `https://${contact.linkedin}`;
        parts.push(`<a href="${BlockRenderer.escapeHtml(url)}" target="_blank" contenteditable="true" data-edit="contact-linkedin">${BlockRenderer.escapeHtml(contact.linkedin)}</a>`);
      }
      if (contact.github) {
        const url = contact.github.startsWith('http') ? contact.github : `https://${contact.github}`;
        parts.push(`<a href="${BlockRenderer.escapeHtml(url)}" target="_blank" contenteditable="true" data-edit="contact-github">${BlockRenderer.escapeHtml(contact.github)}</a>`);
      }
      if (contact.portfolio) {
        const url = contact.portfolio.startsWith('http') ? contact.portfolio : `https://${contact.portfolio}`;
        parts.push(`<a href="${BlockRenderer.escapeHtml(url)}" target="_blank" contenteditable="true" data-edit="contact-portfolio">${BlockRenderer.escapeHtml(contact.portfolio)}</a>`);
      }

      if (parts.length > 0) {
        html += `<div class="contact-line">${parts.join('<span class="contact-sep">|</span>')}</div>`;
      }

      headerDiv.innerHTML = html;
      block.appendChild(headerDiv);
      return block;
    }

    static renderSection(secKey, resume) {
      const headings = resume.section_headings || {};

      switch (secKey) {
        case 'summary': {
          if (!resume.summary) return null;
          const block = BlockRenderer.createBlockWrapper('section-summary', 'summary');
          const title = headings.summary || 'Professional Summary';
          block.innerHTML += `
            <div class="section-title" contenteditable="true" data-edit="section-heading" data-section="summary">${BlockRenderer.escapeHtml(title)}</div>
            <p class="summary-text" contenteditable="true" data-edit="summary">${BlockRenderer.escapeHtml(resume.summary)}</p>
          `;
          return block;
        }

        case 'skills': {
          const skills = resume.skills || [];
          if (!skills || skills.length === 0) return null;
          const block = BlockRenderer.createBlockWrapper('section-skills', 'skills');
          const title = headings.skills || 'Technical Skills';
          let body = `<div class="section-title" contenteditable="true" data-edit="section-heading" data-section="skills">${BlockRenderer.escapeHtml(title)}</div>`;

          const categorized = BlockRenderer.categorizeSkills(skills);
          for (const [catName, catItems] of Object.entries(categorized)) {
            if (catItems && catItems.length > 0) {
              body += `
                <div class="skill-category" data-cat="${BlockRenderer.escapeHtml(catName)}">
                  <span class="skill-category-label" contenteditable="true" data-edit="skill-cat-label">${BlockRenderer.escapeHtml(catName)}:</span>
                  <span class="skill-category-list" contenteditable="true" data-edit="skills-list">${BlockRenderer.escapeHtml(catItems.join(', '))}</span>
                </div>
              `;
            }
          }
          block.innerHTML += body;
          return block;
        }

        case 'experience': {
          const expList = resume.experience || [];
          if (!expList || expList.length === 0) return null;
          const container = document.createElement('div');
          container.className = 'experience-section-wrapper';
          const title = headings.experience || 'Professional Experience';

          const titleBlock = BlockRenderer.createBlockWrapper('exp-header', 'section-header');
          titleBlock.innerHTML += `<div class="section-title" contenteditable="true" data-edit="section-heading" data-section="experience">${BlockRenderer.escapeHtml(title)}</div>`;
          container.appendChild(titleBlock);

          expList.forEach((exp, idx) => {
            const block = BlockRenderer.createBlockWrapper(`exp-${idx}`, 'experience-entry');
            block.setAttribute('data-index', idx);

            const roleTitle = exp.title || exp.role || 'Job Title';
            const company = exp.company || 'Company Name';
            const dates = exp.dates || exp.date || (exp.start_date ? `${exp.start_date} - ${exp.end_date || 'Present'}` : '');
            const loc = exp.location || '';
            const bullets = exp.bullets || [];

            let entryHtml = `
              <div class="entry-item exp-item">
                <div class="two-col-line">
                  <span class="two-col-left role-title" contenteditable="true" data-edit="exp-title">${BlockRenderer.escapeHtml(roleTitle)}</span>
                  ${dates ? `<span class="two-col-right role-dates" contenteditable="true" data-edit="exp-dates">${BlockRenderer.escapeHtml(dates)}</span>` : ''}
                </div>
                ${company || loc ? `
                  <div class="sub-line">
                    <span class="sub-left role-company" contenteditable="true" data-edit="exp-company">${BlockRenderer.escapeHtml(company)}</span>
                    ${loc ? `<span class="sub-right role-location" contenteditable="true" data-edit="exp-loc">${BlockRenderer.escapeHtml(loc)}</span>` : ''}
                  </div>
                ` : ''}
            `;

            entryHtml += `<ul class="bullet-list" data-edit="bullet-list">`;
            if (bullets.length > 0) {
              bullets.forEach(b => {
                if (b && String(b).trim().length > 0) {
                  entryHtml += `<li class="bullet-item" contenteditable="true" data-edit="bullet">${BlockRenderer.escapeHtml(b)}</li>`;
                }
              });
            } else {
              entryHtml += `<li class="bullet-item" contenteditable="true" data-edit="bullet">Key achievement or quantified business outcome...</li>`;
            }
            entryHtml += `</ul></div>`;

            block.innerHTML += entryHtml;
            container.appendChild(block);
          });
          return container;
        }

        case 'education': {
          const eduList = resume.education || [];
          if (!eduList || eduList.length === 0) return null;
          const block = BlockRenderer.createBlockWrapper('section-education', 'education');
          const title = headings.education || 'Education';
          let body = `<div class="section-title" contenteditable="true" data-edit="section-heading" data-section="education">${BlockRenderer.escapeHtml(title)}</div>`;

          eduList.forEach((edu) => {
            const inst = edu.institution || '';
            const deg = edu.degree || '';
            const fld = edu.field || '';
            const gdate = edu.graduation_date || edu.grad_date || edu.date || edu.year || '';
            const gpa = edu.gpa || '';
            const degTitle = deg && fld && !deg.toLowerCase().endsWith('in') ? `${deg} in ${fld}` : (deg || fld || inst);

            body += `
              <div class="entry-item">
                <div class="two-col-line">
                  <span class="two-col-left" contenteditable="true" data-edit="edu-degree">${BlockRenderer.escapeHtml(degTitle)}</span>
                  ${gdate ? `<span class="two-col-right" contenteditable="true" data-edit="edu-date">${BlockRenderer.escapeHtml(gdate)}</span>` : ''}
                </div>
                ${inst && degTitle !== inst ? `
                  <div class="sub-line"><span class="sub-left" contenteditable="true" data-edit="edu-school">${BlockRenderer.escapeHtml(inst)}</span></div>
                ` : ''}
                ${gpa ? `<div class="gpa-line" contenteditable="true" data-edit="edu-gpa">GPA: ${BlockRenderer.escapeHtml(gpa)}</div>` : ''}
              </div>
            `;
          });
          block.innerHTML += body;
          return block;
        }

        case 'certifications': {
          const certs = resume.certifications || [];
          if (!certs || certs.length === 0) return null;
          const block = BlockRenderer.createBlockWrapper('section-certifications', 'certifications');
          const title = headings.certifications || 'Certifications';
          let body = `<div class="section-title" contenteditable="true" data-edit="section-heading" data-section="certifications">${BlockRenderer.escapeHtml(title)}</div><ul class="bullet-list">`;
          certs.forEach(c => {
            if (c) body += `<li class="bullet-item" contenteditable="true" data-edit="bullet">${BlockRenderer.escapeHtml(c)}</li>`;
          });
          body += `</ul>`;
          block.innerHTML += body;
          return block;
        }

        case 'projects': {
          const projects = resume.projects || [];
          if (!projects || projects.length === 0) return null;
          const block = BlockRenderer.createBlockWrapper('section-projects', 'projects');
          const title = headings.projects || 'Key Projects';
          let body = `<div class="section-title" contenteditable="true" data-edit="section-heading" data-section="projects">${BlockRenderer.escapeHtml(title)}</div>`;

          projects.forEach((proj) => {
            const pTitle = proj.title || proj.name || 'Project Name';
            const tech = proj.technologies ? ` (${Array.isArray(proj.technologies) ? proj.technologies.join(', ') : proj.technologies})` : '';
            const pDate = proj.date || proj.dates || '';
            const bullets = proj.bullets || [];

            body += `
              <div class="entry-item">
                <div class="two-col-line">
                  <span class="two-col-left" contenteditable="true" data-edit="proj-title">${BlockRenderer.escapeHtml(pTitle + tech)}</span>
                  ${pDate ? `<span class="two-col-right" contenteditable="true" data-edit="proj-date">${BlockRenderer.escapeHtml(pDate)}</span>` : ''}
                </div>
            `;

            if (bullets.length > 0) {
              body += `<ul class="bullet-list">`;
              bullets.forEach(b => {
                if (b) body += `<li class="bullet-item" contenteditable="true" data-edit="bullet">${BlockRenderer.escapeHtml(b)}</li>`;
              });
              body += `</ul>`;
            }
            body += `</div>`;
          });
          block.innerHTML += body;
          return block;
        }

        default:
          return null;
      }
    }

    static categorizeSkills(skills) {
      if (!Array.isArray(skills)) return { Skills: [] };
      if (skills.length > 0 && typeof skills[0] === 'object' && skills[0].category) {
        const out = {};
        for (const item of skills) {
          out[item.category] = item.items || [];
        }
        return out;
      }

      const cats = {
        'Languages': [],
        'Frameworks & Libraries': [],
        'Cloud & DevOps': [],
        'Databases & Tools': []
      };

      const langRegex = /^(python|java|javascript|typescript|c\+\+|c#|go|golang|rust|ruby|php|scala|swift|kotlin|sql|bash|r)$/i;
      const devopsRegex = /^(aws|azure|gcp|docker|kubernetes|terraform|ci\/cd|jenkins|git|linux|helm|ansible|grafana|prometheus)$/i;
      const dbRegex = /^(postgresql|mysql|mongodb|redis|cassandra|elasticsearch|dynamodb|oracle|snowflake|bigquery|kafka|rabbitmq)$/i;

      for (const skill of skills) {
        const s = String(skill).trim();
        if (langRegex.test(s)) {
          cats['Languages'].push(s);
        } else if (devopsRegex.test(s)) {
          cats['Cloud & DevOps'].push(s);
        } else if (dbRegex.test(s)) {
          cats['Databases & Tools'].push(s);
        } else {
          cats['Frameworks & Libraries'].push(s);
        }
      }

      const finalCats = {};
      for (const [k, v] of Object.entries(cats)) {
        if (v.length > 0) finalCats[k] = v;
      }
      return Object.keys(finalCats).length > 0 ? finalCats : { 'Technical Skills': skills };
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 3. SELECTION MANAGER (Block Focusing, Inspector Sync)
  // ═══════════════════════════════════════════════════════════════════

  class SelectionManager {
    static init() {
      const artboard = document.getElementById('editorArtboard');
      if (!artboard) return;

      artboard.addEventListener('click', (e) => {
        const block = e.target.closest('.editor-block');
        if (!block) {
          if (!e.target.closest('.floating-toolbar') && !e.target.closest('.block-actions-bar')) {
            SelectionManager.clearSelection();
          }
          return;
        }

        const blockId = block.getAttribute('data-block-id');
        if (store.state.selectedBlockId !== blockId) {
          SelectionManager.selectBlock(block);
        }
      });

      const workspace = document.getElementById('editorWorkspace');
      if (workspace) {
        workspace.addEventListener('click', (e) => {
          if (e.target === workspace || e.target.id === 'editorViewport') {
            SelectionManager.clearSelection();
          }
        });
      }
    }

    static selectBlock(blockEl) {
      if (!blockEl) return;
      document.querySelectorAll('.editor-block.selected').forEach(el => el.classList.remove('selected'));
      blockEl.classList.add('selected');
      const blockId = blockEl.getAttribute('data-block-id');
      store.selectBlock(blockId);
      InspectorController.syncWithSelectedBlock(blockEl);

      const target = blockEl.querySelector('.bullet-item, .summary-text, .candidate-name, .section-title, .role-title');
      if (target && typeof AiPolishController !== 'undefined') {
        AiPolishController.setTarget(target, target.innerText);
      }
    }

    static clearSelection() {
      document.querySelectorAll('.editor-block.selected').forEach(el => el.classList.remove('selected'));
      store.clearSelection();
      InspectorController.showEmpty();
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 4. INLINE TEXT EDITOR (Word-Level Direct Editing, Bullets, Spacing)
  // ═══════════════════════════════════════════════════════════════════

  class InlineEditor {
    static activeElement = null;
    static debounceTimer = null;

    static init() {
      InlineEditor.attachAllListeners();

      // Floating toolbar actions
      const floatBar = document.getElementById('floatingToolbar');
      if (floatBar) {
        floatBar.addEventListener('mousedown', (e) => e.preventDefault());
        floatBar.addEventListener('click', (e) => {
          const btn = e.target.closest('.toolbar-btn');
          if (!btn) return;

          if (btn.id === 'floatBtnAi') {
            const sel = window.getSelection();
            const text = sel ? sel.toString().trim() : '';
            if (typeof AiPolishController !== 'undefined') {
              AiPolishController.openAiStudioWithText(InlineEditor.activeElement, text || InlineEditor.activeElement?.innerText);
            }
            return;
          }

          const cmd = btn.getAttribute('data-cmd');
          if (cmd) {
            document.execCommand(cmd, false, null);
            InlineEditor.syncDomToResumeJson();
            store.pushSnapshot(`Format ${cmd}`);
            AutoSaver.trigger();
          }
        });
      }
    }

    static attachAllListeners() {
      const artboard = document.getElementById('editorArtboard');
      if (!artboard) return;

      // Make sure all editable elements have contenteditable="true"
      const editables = artboard.querySelectorAll('[contenteditable="true"], [data-edit]');
      editables.forEach(el => {
        if (!el.hasAttribute('contenteditable')) {
          el.setAttribute('contenteditable', 'true');
        }

        // Focus event
        el.onfocus = () => {
          InlineEditor.activeElement = el;
          const block = el.closest('.editor-block');
          if (block && !block.classList.contains('selected')) {
            SelectionManager.selectBlock(block);
          }
          if (typeof AiPolishController !== 'undefined') {
            AiPolishController.setTarget(el, el.innerText);
          }
        };

        // Input event (real-time debounced auto-save)
        el.oninput = () => {
          clearTimeout(InlineEditor.debounceTimer);
          InlineEditor.debounceTimer = setTimeout(() => {
            InlineEditor.syncDomToResumeJson();
            PageOverflowDetector.check();
            AutoSaver.trigger();
          }, 350);
        };

        // Paste event (clean plain text paste)
        el.onpaste = (e) => {
          e.preventDefault();
          const text = (e.clipboardData || window.clipboardData).getData('text/plain');
          document.execCommand('insertText', false, text);
          InlineEditor.syncDomToResumeJson();
        };

        // Keydown handler (Enter on bullets, Shift+Enter for spacing, Backspace)
        el.onkeydown = (e) => {
          if (el.classList.contains('bullet-item') || el.getAttribute('data-edit') === 'bullet') {
            InlineEditor.handleBulletKeydown(e, el);
          } else if (e.key === 'Enter') {
            if (e.shiftKey) {
              // Shift+Enter inserts a soft break for spacing
              e.preventDefault();
              document.execCommand('insertLineBreak');
            } else if (el.classList.contains('candidate-name') || el.classList.contains('section-title') || el.classList.contains('two-col-left') || el.classList.contains('two-col-right')) {
              // Heading enter prevents breaking the layout line
              e.preventDefault();
            }
          }
        };
      });

      // Wire Block Action Buttons (Move Up, Move Down, Space, AI, Delete)
      artboard.querySelectorAll('.editor-block').forEach(block => {
        const bar = block.querySelector('.block-actions-bar');
        if (!bar) return;

        bar.querySelector('.btn-move-up')?.addEventListener('click', (e) => {
          e.stopPropagation();
          InlineEditor.moveBlock(block, -1);
        });

        bar.querySelector('.btn-move-down')?.addEventListener('click', (e) => {
          e.stopPropagation();
          InlineEditor.moveBlock(block, 1);
        });

        bar.querySelector('.btn-add-space')?.addEventListener('click', (e) => {
          e.stopPropagation();
          InlineEditor.adjustBlockSpacing(block, 4);
        });

        bar.querySelector('.btn-add-bullet')?.addEventListener('click', (e) => {
          e.stopPropagation();
          InlineEditor.addBulletToBlock(block);
        });

        bar.querySelector('.btn-ai-polish')?.addEventListener('click', (e) => {
          e.stopPropagation();
          const target = block.querySelector('.bullet-item, .summary-text, .candidate-name, .section-title');
          if (typeof AiPolishController !== 'undefined') {
            AiPolishController.openAiStudioWithText(target, target?.innerText);
          }
        });

        bar.querySelector('.btn-delete-block')?.addEventListener('click', (e) => {
          e.stopPropagation();
          InlineEditor.deleteBlock(block);
        });
      });
    }

    /**
     * MS Word-level Bullet Keyboard Handling:
     * - Enter creates new bullet point, splits text if in middle, moves caret to new bullet.
     * - Backspace on empty bullet removes it and merges into previous.
     * - Shift+Enter inserts line break for multi-line spacing.
     */
    static handleBulletKeydown(e, li) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const sel = window.getSelection();
        let remainderText = '';

        if (sel && sel.rangeCount > 0) {
          const range = sel.getRangeAt(0);
          const endRange = range.cloneRange();
          endRange.selectNodeContents(li);
          endRange.setStart(range.endContainer, range.endOffset);
          remainderText = endRange.toString();
          endRange.deleteContents();
        }

        // Create new sibling bullet item
        const newLi = document.createElement('li');
        newLi.className = 'bullet-item';
        newLi.setAttribute('contenteditable', 'true');
        newLi.setAttribute('data-edit', 'bullet');
        newLi.innerHTML = remainderText.trim() ? BlockRenderer.escapeHtml(remainderText) : '<br>';

        li.parentNode.insertBefore(newLi, li.nextSibling);

        // Move caret to start of new bullet
        const newRange = document.createRange();
        newRange.setStart(newLi, 0);
        newRange.collapse(true);
        sel.removeAllRanges();
        sel.addRange(newRange);
        newLi.focus();

        InlineEditor.attachAllListeners();
        InlineEditor.syncDomToResumeJson();
        store.pushSnapshot('Add Bullet Point');
        PageOverflowDetector.check();
        AutoSaver.trigger();
      } else if (e.key === 'Backspace') {
        const text = li.innerText.replace(/\uFEFF/g, '').trim();
        const sel = window.getSelection();
        const isAtStart = sel && sel.rangeCount > 0 && sel.getRangeAt(0).startOffset === 0;

        if (text === '' || isAtStart) {
          const prevLi = li.previousElementSibling;
          if (prevLi && prevLi.classList.contains('bullet-item')) {
            e.preventDefault();
            const origLen = prevLi.innerText.length;
            if (text !== '') {
              prevLi.innerHTML += li.innerHTML;
            }
            li.remove();

            // Place caret at merge point in previous bullet
            const newRange = document.createRange();
            const textNode = prevLi.lastChild || prevLi;
            newRange.setStart(textNode, textNode.nodeType === Node.TEXT_NODE ? textNode.length : 0);
            newRange.collapse(true);
            sel.removeAllRanges();
            sel.addRange(newRange);
            prevLi.focus();

            InlineEditor.syncDomToResumeJson();
            store.pushSnapshot('Delete Bullet Point');
            PageOverflowDetector.check();
            AutoSaver.trigger();
          }
        }
      } else if (e.key === 'Enter' && e.shiftKey) {
        e.preventDefault();
        document.execCommand('insertLineBreak');
      }
    }

    static addBulletToBlock(block) {
      const list = block.querySelector('.bullet-list');
      if (!list) return;

      const newLi = document.createElement('li');
      newLi.className = 'bullet-item';
      newLi.setAttribute('contenteditable', 'true');
      newLi.setAttribute('data-edit', 'bullet');
      newLi.innerText = 'Key achievement or quantifiable business impact...';
      list.appendChild(newLi);

      InlineEditor.attachAllListeners();
      newLi.focus();

      // Select all text in new bullet so user can immediately type over it
      const sel = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(newLi);
      sel.removeAllRanges();
      sel.addRange(range);

      InlineEditor.syncDomToResumeJson();
      store.pushSnapshot('Add Bullet');
      PageOverflowDetector.check();
      AutoSaver.trigger();
    }

    static adjustBlockSpacing(block, deltaPx) {
      const currentMb = parseFloat(window.getComputedStyle(block).marginBottom) || 0;
      const newMb = Math.max(0, currentMb + deltaPx);
      block.style.marginBottom = `${newMb}px`;

      const inspMb = document.getElementById('inspMarginBottom');
      const inspSlider = document.getElementById('inspSliderMarginBottom');
      if (inspMb) inspMb.value = newMb;
      if (inspSlider) inspSlider.value = newMb;

      store.pushSnapshot(`Adjust Section Spacing (${newMb}px)`);
      PageOverflowDetector.check();
      AutoSaver.trigger();
    }

    static moveBlock(block, direction) {
      if (direction === -1) {
        const prev = block.previousElementSibling;
        if (prev && prev.classList.contains('editor-block') && prev.getAttribute('data-block-id') !== 'header') {
          block.parentNode.insertBefore(block, prev);
          InlineEditor.pulseBlock(block);
          store.pushSnapshot('Move Block Up');
          AutoSaver.trigger();
        }
      } else if (direction === 1) {
        const next = block.nextElementSibling;
        if (next && next.classList.contains('editor-block')) {
          block.parentNode.insertBefore(next, block);
          InlineEditor.pulseBlock(block);
          store.pushSnapshot('Move Block Down');
          AutoSaver.trigger();
        }
      }
    }

    static deleteBlock(block) {
      const type = block.getAttribute('data-block-type') || 'section';
      if (!confirm(`Are you sure you want to delete this ${type}? (You can Undo with Ctrl+Z)`)) return;

      block.remove();
      SelectionManager.clearSelection();
      InlineEditor.syncDomToResumeJson();
      store.pushSnapshot(`Delete ${type}`);
      PageOverflowDetector.check();
      AutoSaver.trigger();
    }

    static pulseBlock(block) {
      block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      block.classList.add('selected');
      setTimeout(() => SelectionManager.selectBlock(block), 100);
    }

    static showFloatingToolbarForRange(range) {
      const bar = document.getElementById('floatingToolbar');
      if (!bar) return;

      const rect = range.getBoundingClientRect();
      const barH = 38;
      let top = rect.top - barH - 8;
      let left = rect.left + (rect.width / 2) - 130;

      if (top < 56) top = rect.bottom + 8;
      if (left < 10) left = 10;

      bar.style.top = `${Math.round(top)}px`;
      bar.style.left = `${Math.round(left)}px`;
      bar.classList.add('visible');
    }

    static hideFloatingToolbar() {
      const bar = document.getElementById('floatingToolbar');
      if (bar) bar.classList.remove('visible');
    }

    static syncDomToResumeJson() {
      const r = store.state.resume;
      const getTxt = (sel) => {
        const el = document.querySelector(sel);
        return el ? el.innerText.trim() : '';
      };

      const name = getTxt('.candidate-name');
      if (name) r.name = name;

      const role = getTxt('.target-role');
      if (role !== undefined) r.target_role = role;

      if (!r.contact) r.contact = {};
      const em = getTxt('[data-edit="contact-email"]');
      if (em) r.contact.email = em;
      const ph = getTxt('[data-edit="contact-phone"]');
      if (ph) r.contact.phone = ph;
      const loc = getTxt('[data-edit="contact-location"]');
      if (loc) r.contact.location = loc;

      const summary = getTxt('.summary-text[data-edit="summary"]');
      if (summary) r.summary = summary;

      // Scrape experience entries
      const expBlocks = document.querySelectorAll('.editor-block[data-block-type="experience-entry"]');
      if (expBlocks.length > 0) {
        r.experience = [];
        expBlocks.forEach((eb) => {
          const title = eb.querySelector('[data-edit="exp-title"]')?.innerText.trim() || '';
          const comp = eb.querySelector('[data-edit="exp-company"]')?.innerText.trim() || '';
          const dt = eb.querySelector('[data-edit="exp-dates"]')?.innerText.trim() || '';
          const locEl = eb.querySelector('[data-edit="exp-loc"]')?.innerText.trim() || '';

          const bullets = [];
          eb.querySelectorAll('.bullet-item[data-edit="bullet"]').forEach(li => {
            const bText = li.innerText.trim();
            if (bText) bullets.push(bText);
          });

          r.experience.push({
            title,
            company: comp,
            dates: dt,
            location: locEl,
            bullets
          });
        });
      }

      // Scrape certifications
      const certBullets = document.querySelectorAll('[data-block-type="certifications"] .bullet-item');
      if (certBullets.length > 0) {
        r.certifications = [];
        certBullets.forEach(li => {
          const t = li.innerText.trim();
          if (t) r.certifications.push(t);
        });
      }

      // Scrape skills
      const skillRows = document.querySelectorAll('[data-block-type="skills"] .skill-category');
      if (skillRows.length > 0) {
        const skillsObj = [];
        skillRows.forEach(row => {
          const label = row.querySelector('.skill-category-label')?.innerText.replace(':', '').trim();
          const listTxt = row.querySelector('.skill-category-list')?.innerText.trim() || '';
          const items = listTxt.split(',').map(s => s.trim()).filter(Boolean);
          if (label && items.length > 0) {
            skillsObj.push({ category: label, items });
          }
        });
        if (skillsObj.length > 0) r.skills = skillsObj;
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 5. TOOLBAR CONTROLLER (Selection-Aware Font Sizing, Word Parity)
  // ═══════════════════════════════════════════════════════════════════

  class ToolbarController {
    static init() {
      // Prevent focus/selection drop when clicking ANY toolbar button
      const toolbar = document.getElementById('editorToolbar');
      if (toolbar) {
        toolbar.addEventListener('mousedown', (e) => {
          if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'SELECT') {
            e.preventDefault();
          }
        });
      }

      // Back button
      document.getElementById('btnBack')?.addEventListener('click', () => {
        const config = window.EDITOR_CONFIG || {};
        window.location.href = config.backUrl || '/';
      });

      // Top Toolbar AI Polish Button
      document.getElementById('btnToolbarAi')?.addEventListener('click', () => {
        const sel = window.getSelection();
        const text = sel ? sel.toString().trim() : '';
        const target = InlineEditor.activeElement || document.querySelector('.bullet-item') || document.querySelector('.summary-text');
        if (typeof AiPolishController !== 'undefined') {
          AiPolishController.openAiStudioWithText(target, text || target?.innerText);
        }
      });

      // Dynamic Selection Change Listener (Reads cursor computed styles)
      document.addEventListener('selectionchange', () => {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return;
        const range = sel.getRangeAt(0);

        const container = range.commonAncestorContainer;
        const el = container.nodeType === Node.ELEMENT_NODE ? container : container.parentElement;
        const artboard = document.getElementById('editorArtboard');
        if (!el || !artboard || !artboard.contains(el)) return;

        // 1. Read computed font size at cursor and sync fontSizeInput
        const computed = window.getComputedStyle(el);
        const sizePx = parseFloat(computed.fontSize);
        const sizePt = Math.round((sizePx * 0.75) * 2) / 2; // 1pt ≈ 1.333px

        const sizeInput = document.getElementById('fontSizeInput');
        if (sizeInput && document.activeElement !== sizeInput) {
          sizeInput.value = sizePt;
        }

        // 2. Read computed font family and sync fontFamilySelect
        const fontSelect = document.getElementById('fontFamilySelect');
        if (fontSelect && document.activeElement !== fontSelect) {
          const fam = computed.fontFamily.replace(/['"]/g, '').split(',')[0].trim().toLowerCase();
          for (const opt of fontSelect.options) {
            if (opt.value.toLowerCase() === fam) {
              fontSelect.value = opt.value;
              break;
            }
          }
        }

        // 3. Sync Bold, Italic, Underline button states
        const isBold = computed.fontWeight >= 600 || computed.fontWeight === 'bold';
        const isItalic = computed.fontStyle === 'italic';
        const isUnderline = computed.textDecorationLine.includes('underline');

        document.getElementById('btnBold')?.classList.toggle('active', isBold);
        document.getElementById('btnItalic')?.classList.toggle('active', isItalic);
        document.getElementById('btnUnderline')?.classList.toggle('active', isUnderline);

        // 4. Update AI Polish Target & Floating Toolbar
        if (!sel.isCollapsed && sel.toString().trim().length > 0) {
          if (typeof AiPolishController !== 'undefined') {
            AiPolishController.setTarget(el, sel.toString().trim());
          }
          InlineEditor.showFloatingToolbarForRange(range);
        } else {
          InlineEditor.hideFloatingToolbar();
          if (typeof AiPolishController !== 'undefined' && el) {
            AiPolishController.setTarget(el, el.innerText.trim());
          }
        }
      });

      // Selection-Aware Font Size Stepper & Input
      const sizeInput = document.getElementById('fontSizeInput');
      const btnSizeDec = document.getElementById('btnSizeDec');
      const btnSizeInc = document.getElementById('btnSizeInc');

      if (sizeInput) {
        sizeInput.addEventListener('change', () => {
          const newPt = parseFloat(sizeInput.value) || 9.5;
          ToolbarController.applyFontSize(newPt);
        });

        btnSizeDec?.addEventListener('click', () => {
          let val = (parseFloat(sizeInput.value) || 9.5) - 0.5;
          if (val < 6) val = 6;
          sizeInput.value = val;
          ToolbarController.applyFontSize(val);
        });

        btnSizeInc?.addEventListener('click', () => {
          let val = (parseFloat(sizeInput.value) || 9.5) + 0.5;
          if (val > 36) val = 36;
          sizeInput.value = val;
          ToolbarController.applyFontSize(val);
        });
      }

      // Font Family Dropdown
      const fontSelect = document.getElementById('fontFamilySelect');
      if (fontSelect) {
        fontSelect.addEventListener('change', (e) => {
          const font = e.target.value;
          ToolbarController.applyFontFamily(font);
        });
      }

      // Formatting: Bold, Italic, Underline, Strikethrough
      const bindExec = (id, cmd) => {
        const btn = document.getElementById(id);
        if (btn) {
          btn.addEventListener('click', () => {
            document.execCommand(cmd, false, null);
            InlineEditor.syncDomToResumeJson();
            store.pushSnapshot(`Format ${cmd}`);
            AutoSaver.trigger();
          });
        }
      };
      bindExec('btnBold', 'bold');
      bindExec('btnItalic', 'italic');
      bindExec('btnUnderline', 'underline');
      bindExec('btnStrike', 'strikeThrough');

      // Alignment
      document.getElementById('btnAlignLeft')?.addEventListener('click', () => ToolbarController.applyAlignment('left'));
      document.getElementById('btnAlignCenter')?.addEventListener('click', () => ToolbarController.applyAlignment('center'));
      document.getElementById('btnAlignRight')?.addEventListener('click', () => ToolbarController.applyAlignment('right'));
      document.getElementById('btnAlignJustify')?.addEventListener('click', () => ToolbarController.applyAlignment('justify'));

      // Case cycling
      document.getElementById('btnCase')?.addEventListener('click', () => {
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;
        const text = sel.toString();
        let newText = text;
        if (text === text.toUpperCase()) {
          newText = text.toLowerCase();
        } else if (text === text.toLowerCase()) {
          newText = text.replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.substr(1).toLowerCase());
        } else {
          newText = text.toUpperCase();
        }
        document.execCommand('insertText', false, newText);
        InlineEditor.syncDomToResumeJson();
        store.pushSnapshot('Change Case');
      });

      // Undo / Redo
      document.getElementById('btnUndo')?.addEventListener('click', () => store.undo());
      document.getElementById('btnRedo')?.addEventListener('click', () => store.redo());
    }

    /**
     * Exact MS Word / Google Docs font sizing:
     * 1. If text is highlighted: wraps selection in <span style="font-size: ...pt">
     * 2. If cursor inside an element (heading, title, name, bullet): modifies that element's style.fontSize
     * 3. Fallback: updates document base font size
     */
    static applyFontSize(newPt) {
      const sel = window.getSelection();
      const artboard = document.getElementById('editorArtboard');

      // 1. Text is selected (highlighted)
      if (sel && sel.rangeCount > 0 && !sel.isCollapsed) {
        const range = sel.getRangeAt(0);
        if (artboard && artboard.contains(range.commonAncestorContainer)) {
          const span = document.createElement('span');
          span.style.fontSize = `${newPt}pt`;
          span.style.lineHeight = '1.25';

          try {
            const contents = range.extractContents();
            span.appendChild(contents);
            range.insertNode(span);

            // Re-select newly wrapped text
            sel.removeAllRanges();
            const newRange = document.createRange();
            newRange.selectNodeContents(span);
            sel.addRange(newRange);
          } catch (err) {
            document.execCommand('fontSize', false, '7');
          }

          InlineEditor.syncDomToResumeJson();
          store.pushSnapshot(`Font Size ${newPt}pt on Selection`);
          AutoSaver.trigger();
          return;
        }
      }

      // 2. An active editable element is focused
      const active = InlineEditor.activeElement || document.activeElement;
      if (active && artboard && artboard.contains(active) && active.hasAttribute('contenteditable')) {
        active.style.fontSize = `${newPt}pt`;
        InlineEditor.syncDomToResumeJson();
        store.pushSnapshot(`Font Size ${newPt}pt on ${active.className || 'Element'}`);
        AutoSaver.trigger();
        return;
      }

      // 3. Fallback: update document base font size
      store.updateStyle('typography', 'fontSize', `${newPt}pt`);
    }

    static applyFontFamily(font) {
      const sel = window.getSelection();
      const artboard = document.getElementById('editorArtboard');

      if (sel && sel.rangeCount > 0 && !sel.isCollapsed) {
        const range = sel.getRangeAt(0);
        if (artboard && artboard.contains(range.commonAncestorContainer)) {
          const span = document.createElement('span');
          span.style.fontFamily = `'${font}', sans-serif`;
          const contents = range.extractContents();
          span.appendChild(contents);
          range.insertNode(span);

          sel.removeAllRanges();
          const newRange = document.createRange();
          newRange.selectNodeContents(span);
          sel.addRange(newRange);

          InlineEditor.syncDomToResumeJson();
          store.pushSnapshot(`Font Family ${font} on Selection`);
          AutoSaver.trigger();
          return;
        }
      }

      const active = InlineEditor.activeElement || document.activeElement;
      if (active && artboard && artboard.contains(active) && active.hasAttribute('contenteditable')) {
        active.style.fontFamily = `'${font}', sans-serif`;
        InlineEditor.syncDomToResumeJson();
        store.pushSnapshot(`Font Family ${font} on ${active.className}`);
        AutoSaver.trigger();
        return;
      }

      store.updateStyle('typography', 'fontFamily', font);
    }

    static applyAlignment(align) {
      const active = InlineEditor.activeElement || document.activeElement;
      const block = active ? active.closest('.editor-block') : document.querySelector('.editor-block.selected');

      if (active && active.hasAttribute('contenteditable')) {
        active.style.textAlign = align;
      } else if (block) {
        block.style.textAlign = align;
      }

      InlineEditor.syncDomToResumeJson();
      store.pushSnapshot(`Align ${align}`);
      AutoSaver.trigger();
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 6. SPACING POPOVER CONTROLLER (Live Sliders from Top Bar)
  // ═══════════════════════════════════════════════════════════════════

  class SpacingPopoverController {
    static init() {
      const btnSpacing = document.getElementById('btnSpacing');
      const popover = document.getElementById('spacingPopover');
      if (!btnSpacing || !popover) return;

      btnSpacing.addEventListener('click', (e) => {
        e.stopPropagation();
        const isVis = popover.classList.contains('visible');
        if (isVis) {
          popover.classList.remove('visible');
        } else {
          const rect = btnSpacing.getBoundingClientRect();
          popover.style.top = `${rect.bottom + 6}px`;
          popover.style.left = `${Math.max(10, rect.left - 40)}px`;
          popover.classList.add('visible');
          SpacingPopoverController.syncValues();
        }
      });

      document.addEventListener('click', (e) => {
        if (!popover.contains(e.target) && e.target !== btnSpacing) {
          popover.classList.remove('visible');
        }
      });

      const bindSlider = (sliderId, labelId, cat, key, fmt) => {
        const slider = document.getElementById(sliderId);
        const label = document.getElementById(labelId);
        if (!slider) return;

        slider.addEventListener('input', () => {
          const val = fmt(slider.value);
          if (label) label.innerText = val;
          store.updateStyle(cat, key, val);
          PageOverflowDetector.check();
        });
      };

      bindSlider('sliderLineHeight', 'valLineHeight', 'typography', 'lineHeight', v => (v / 100).toFixed(2));
      bindSlider('sliderLetterSpacing', 'valLetterSpacing', 'typography', 'letterSpacing', v => `${(v / 100).toFixed(1)}px`);
      bindSlider('sliderSectionGap', 'valSectionGap', 'spacing', 'sectionGap', v => `${v}px`);
      bindSlider('sliderEntryGap', 'valEntryGap', 'spacing', 'entryGap', v => `${v}px`);
      bindSlider('sliderBulletGap', 'valBulletGap', 'spacing', 'bulletGap', v => `${v}px`);

      document.getElementById('btnSpacingReset')?.addEventListener('click', () => {
        store.updateStyle('typography', 'lineHeight', '1.22');
        store.updateStyle('typography', 'letterSpacing', '0px');
        store.updateStyle('spacing', 'sectionGap', '6px');
        store.updateStyle('spacing', 'entryGap', '4px');
        store.updateStyle('spacing', 'bulletGap', '1px');
        SpacingPopoverController.syncValues();
      });
    }

    static syncValues() {
      const { typography, spacing } = store.state.styles;
      const setVal = (sliderId, labelId, val, factor = 1, unit = '') => {
        const s = document.getElementById(sliderId);
        const l = document.getElementById(labelId);
        const num = parseFloat(val) || 0;
        if (s) s.value = Math.round(num * factor);
        if (l) l.innerText = `${num}${unit}`;
      };

      setVal('sliderLineHeight', 'valLineHeight', typography.lineHeight || 1.22, 100);
      setVal('sliderLetterSpacing', 'valLetterSpacing', typography.letterSpacing || 0, 100, 'px');
      setVal('sliderSectionGap', 'valSectionGap', spacing.sectionGap || 6, 1, 'px');
      setVal('sliderEntryGap', 'valEntryGap', spacing.entryGap || 4, 1, 'px');
      setVal('sliderBulletGap', 'valBulletGap', spacing.bulletGap || 1, 1, 'px');
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 7. COLOR POPOVER CONTROLLER
  // ═══════════════════════════════════════════════════════════════════

  class ColorPopoverController {
    static init() {
      const btn = document.getElementById('btnTextColor');
      const popover = document.getElementById('colorPopover');
      const swatch = document.getElementById('colorSwatch');
      const hexInput = document.getElementById('colorHexInput');
      const grid = document.getElementById('colorPresetGrid');
      if (!btn || !popover) return;

      const presets = [
        '#000000', '#1f2937', '#374151', '#4b5563', '#6b7280', '#9ca3af',
        '#1e3a8a', '#1e40af', '#1d4ed8', '#2563eb', '#3b82f6', '#60a5fa',
        '#065f46', '#047857', '#059669', '#10b981', '#34d399', '#6ee7b7',
        '#991b1b', '#b91c1c', '#dc2626', '#ef4444', '#f87171', '#fca5a5'
      ];

      if (grid) {
        grid.innerHTML = '';
        presets.forEach(col => {
          const div = document.createElement('div');
          div.className = 'color-preset-item';
          div.style.background = col;
          div.addEventListener('click', () => {
            ColorPopoverController.applyColor(col);
            popover.classList.remove('visible');
          });
          grid.appendChild(div);
        });
      }

      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isVis = popover.classList.contains('visible');
        if (isVis) {
          popover.classList.remove('visible');
        } else {
          const rect = btn.getBoundingClientRect();
          popover.style.top = `${rect.bottom + 6}px`;
          popover.style.left = `${Math.max(10, rect.left - 60)}px`;
          popover.classList.add('visible');
        }
      });

      document.addEventListener('click', (e) => {
        if (!popover.contains(e.target) && e.target !== btn) {
          popover.classList.remove('visible');
        }
      });

      if (hexInput) {
        hexInput.addEventListener('change', () => {
          ColorPopoverController.applyColor(hexInput.value.trim());
        });
      }
    }

    static applyColor(col) {
      const swatch = document.getElementById('colorSwatch');
      if (swatch) swatch.style.background = col;

      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0 && !sel.isCollapsed) {
        document.execCommand('foreColor', false, col);
        InlineEditor.syncDomToResumeJson();
        store.pushSnapshot('Change Text Color on Selection');
        AutoSaver.trigger();
        return;
      }

      const active = InlineEditor.activeElement || document.activeElement;
      if (active && document.getElementById('editorArtboard').contains(active) && active.hasAttribute('contenteditable')) {
        active.style.color = col;
        InlineEditor.syncDomToResumeJson();
        store.pushSnapshot(`Color on ${active.className}`);
        AutoSaver.trigger();
        return;
      }

      store.updateStyle('colors', 'text', col);
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 8. INSPECTOR CONTROLLER (Section Spacing & De-Congestion)
  // ═══════════════════════════════════════════════════════════════════

  class InspectorController {
    static currentBlock = null;

    static init() {
      // Collapsible headers
      document.querySelectorAll('.inspector-section-header').forEach(header => {
        header.addEventListener('click', () => {
          header.parentElement.classList.toggle('collapsed');
        });
      });

      document.getElementById('btnCloseInspector')?.addEventListener('click', () => {
        SelectionManager.clearSelection();
      });

      // Actions: Move Up, Down, Duplicate, Delete
      document.getElementById('inspMoveUp')?.addEventListener('click', () => {
        if (InspectorController.currentBlock) InlineEditor.moveBlock(InspectorController.currentBlock, -1);
      });
      document.getElementById('inspMoveDown')?.addEventListener('click', () => {
        if (InspectorController.currentBlock) InlineEditor.moveBlock(InspectorController.currentBlock, 1);
      });
      document.getElementById('inspDuplicate')?.addEventListener('click', () => InspectorController.duplicateSelectedBlock());
      document.getElementById('inspDelete')?.addEventListener('click', () => {
        if (InspectorController.currentBlock) InlineEditor.deleteBlock(InspectorController.currentBlock);
      });

      // Active Section Spacing (Space After) Slider & Number Input
      const inspMb = document.getElementById('inspMarginBottom');
      const inspSliderMb = document.getElementById('inspSliderMarginBottom');

      const applySpacing = (val) => {
        const num = Math.max(0, parseInt(val) || 0);
        if (InspectorController.currentBlock) {
          InspectorController.currentBlock.style.marginBottom = `${num}px`;
        }
        if (inspMb) inspMb.value = num;
        if (inspSliderMb) inspSliderMb.value = num;
        store.pushSnapshot(`Section Space After (${num}px)`);
        PageOverflowDetector.check();
        AutoSaver.trigger();
      };

      if (inspMb) {
        inspMb.addEventListener('input', () => applySpacing(inspMb.value));
      }
      if (inspSliderMb) {
        inspSliderMb.addEventListener('input', () => applySpacing(inspSliderMb.value));
      }

      // Quick +4px and -4px Spacing Buttons
      document.getElementById('inspBtnAddSpace')?.addEventListener('click', () => {
        if (InspectorController.currentBlock) {
          InlineEditor.adjustBlockSpacing(InspectorController.currentBlock, 4);
        }
      });
      document.getElementById('inspBtnSubSpace')?.addEventListener('click', () => {
        if (InspectorController.currentBlock) {
          InlineEditor.adjustBlockSpacing(InspectorController.currentBlock, -4);
        }
      });

      // Bullet Gap Input
      const inspBg = document.getElementById('inspBulletGap');
      if (inspBg) {
        inspBg.addEventListener('change', () => {
          const val = `${parseFloat(inspBg.value) || 1}px`;
          store.updateStyle('spacing', 'bulletGap', val);
        });
      }

      // Section Gap Input
      const inspSg = document.getElementById('inspSectionGap');
      if (inspSg) {
        inspSg.addEventListener('change', () => {
          const val = `${parseFloat(inspSg.value) || 6}px`;
          store.updateStyle('spacing', 'sectionGap', val);
        });
      }
    }

    static syncWithSelectedBlock(blockEl) {
      InspectorController.currentBlock = blockEl;
      const empty = document.getElementById('inspectorEmpty');
      const content = document.getElementById('inspectorContent');
      const title = document.getElementById('inspectorTitle');

      if (empty) empty.style.display = 'none';
      if (content) content.style.display = 'block';

      const blockType = blockEl.getAttribute('data-block-type') || 'block';
      const titles = {
        'header': 'Candidate Header',
        'summary': 'Professional Summary',
        'skills': 'Technical Skills',
        'experience-entry': 'Experience Entry',
        'section-header': 'Section Header',
        'education': 'Education Section',
        'certifications': 'Certifications',
        'projects': 'Key Projects'
      };

      if (title) title.innerText = titles[blockType] || 'Section Properties';

      // Read current computed bottom margin of block
      const currentMb = parseInt(window.getComputedStyle(blockEl).marginBottom) || 0;
      const inspMb = document.getElementById('inspMarginBottom');
      const inspSliderMb = document.getElementById('inspSliderMarginBottom');
      if (inspMb) inspMb.value = currentMb;
      if (inspSliderMb) inspSliderMb.value = currentMb;

      // Sync bullet gap
      const inspBg = document.getElementById('inspBulletGap');
      if (inspBg) inspBg.value = parseFloat(store.state.styles.spacing.bulletGap) || 1;

      // Sync global section gap
      const inspSg = document.getElementById('inspSectionGap');
      if (inspSg) inspSg.value = parseFloat(store.state.styles.spacing.sectionGap) || 6;
    }

    static showEmpty() {
      InspectorController.currentBlock = null;
      const empty = document.getElementById('inspectorEmpty');
      const content = document.getElementById('inspectorContent');
      if (empty) empty.style.display = 'block';
      if (content) content.style.display = 'none';
    }

    static duplicateSelectedBlock() {
      if (!InspectorController.currentBlock) return;
      const clone = InspectorController.currentBlock.cloneNode(true);
      clone.setAttribute('data-block-id', `block-${Date.now()}`);
      InspectorController.currentBlock.parentNode.insertBefore(clone, InspectorController.currentBlock.nextSibling);

      InlineEditor.attachAllListeners();
      SelectionManager.selectBlock(clone);
      InlineEditor.syncDomToResumeJson();
      store.pushSnapshot('Duplicate Block');
      PageOverflowDetector.check();
      AutoSaver.trigger();
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 9. SIDEBAR CONTROLLER (Tabs, Presets, Add Section)
  // ═══════════════════════════════════════════════════════════════════

  class SidebarController {
    static init() {
      // Sidebar Tab Switching
      document.querySelectorAll('.sidebar-tab').forEach(tab => {
        tab.addEventListener('click', () => {
          document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
          document.querySelectorAll('.sidebar-panel').forEach(p => p.classList.remove('active'));

          tab.classList.add('active');
          const panelId = tab.getAttribute('data-tab');
          const panel = document.getElementById(`panel${panelId.charAt(0).toUpperCase() + panelId.slice(1)}`);
          if (panel) panel.classList.add('active');
        });
      });

      // Quick Add Section buttons
      document.querySelectorAll('.sidebar-add-btn[data-add]').forEach(btn => {
        btn.addEventListener('click', () => {
          const type = btn.getAttribute('data-add');
          SidebarController.handleAddSection(type);
        });
      });

      // Template presets
      document.querySelectorAll('.template-card').forEach(card => {
        card.addEventListener('click', () => {
          document.querySelectorAll('.template-card').forEach(c => c.classList.remove('active'));
          card.classList.add('active');
          const tpl = card.getAttribute('data-template');
          SidebarController.applyTemplate(tpl);
        });
      });

      // Initialize AI Tools in sidebar
      AiPolishController.init();
    }

    static handleAddSection(type) {
      const container = document.getElementById('resumeContent');
      if (!container) return;

      if (type === 'experience') {
        const block = BlockRenderer.createBlockWrapper(`exp-${Date.now()}`, 'experience-entry');
        block.innerHTML += `
          <div class="entry-item exp-item">
            <div class="two-col-line">
              <span class="two-col-left role-title" contenteditable="true" data-edit="exp-title">Senior Professional Role</span>
              <span class="two-col-right role-dates" contenteditable="true" data-edit="exp-dates">Jan 2024 - Present</span>
            </div>
            <div class="sub-line">
              <span class="sub-left role-company" contenteditable="true" data-edit="exp-company">Enterprise Organization</span>
              <span class="sub-right role-location" contenteditable="true" data-edit="exp-loc">Remote / New York, NY</span>
            </div>
            <ul class="bullet-list" data-edit="bullet-list">
              <li class="bullet-item" contenteditable="true" data-edit="bullet">Spearheaded mission-critical cross-functional initiative increasing overall workflow throughput by 34%.</li>
              <li class="bullet-item" contenteditable="true" data-edit="bullet">Architected high-reliability scalable pipeline resulting in $120K annual infrastructure savings.</li>
            </ul>
          </div>
        `;
        container.appendChild(block);
        InlineEditor.attachAllListeners();
        SelectionManager.selectBlock(block);
      } else if (type === 'summary') {
        const block = BlockRenderer.createBlockWrapper(`summary-${Date.now()}`, 'summary');
        block.innerHTML += `
          <div class="section-title" contenteditable="true" data-edit="section-heading">Professional Summary</div>
          <p class="summary-text" contenteditable="true" data-edit="summary">Results-driven professional with deep technical expertise in high-impact execution, strategic problem solving, and building scalable production solutions.</p>
        `;
        container.insertBefore(block, container.children[1] || null);
        InlineEditor.attachAllListeners();
        SelectionManager.selectBlock(block);
      } else if (type === 'education') {
        const block = BlockRenderer.createBlockWrapper(`edu-${Date.now()}`, 'education');
        block.innerHTML += `
          <div class="section-title" contenteditable="true" data-edit="section-heading">Education</div>
          <div class="entry-item">
            <div class="two-col-line">
              <span class="two-col-left" contenteditable="true" data-edit="edu-degree">Bachelor of Science in Computer Science</span>
              <span class="two-col-right" contenteditable="true" data-edit="edu-date">2020 - 2024</span>
            </div>
            <div class="sub-line"><span class="sub-left" contenteditable="true" data-edit="edu-school">Top Tier University</span></div>
          </div>
        `;
        container.appendChild(block);
        InlineEditor.attachAllListeners();
        SelectionManager.selectBlock(block);
      }

      InlineEditor.syncDomToResumeJson();
      store.pushSnapshot(`Add ${type} Section`);
      PageOverflowDetector.check();
      AutoSaver.trigger();
    }

    static applyTemplate(templateName) {
      const templates = {
        'ats-classic': {
          typography: { fontFamily: 'Carlito', fontSize: '9.5pt', lineHeight: '1.22' },
          spacing: { sectionGap: '6px', entryGap: '4px', bulletGap: '1px' }
        },
        'executive': {
          typography: { fontFamily: 'Georgia', fontSize: '10pt', lineHeight: '1.28' },
          spacing: { sectionGap: '8px', entryGap: '5px', bulletGap: '2px' }
        },
        'modern': {
          typography: { fontFamily: 'Inter', fontSize: '9.5pt', lineHeight: '1.24' },
          spacing: { sectionGap: '6px', entryGap: '3.5px', bulletGap: '1px' }
        },
        'minimalist': {
          typography: { fontFamily: 'Arial', fontSize: '9pt', lineHeight: '1.2' },
          spacing: { sectionGap: '5px', entryGap: '3px', bulletGap: '0.5px' }
        }
      };

      const preset = templates[templateName];
      if (!preset) return;

      Object.assign(store.state.styles.typography, preset.typography);
      Object.assign(store.state.styles.spacing, preset.spacing);
      store.applyStylesToArtboard();
      store.pushSnapshot(`Apply Template: ${templateName}`);
      PageOverflowDetector.check();
      AutoSaver.trigger();
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 10. AI POLISH STUDIO CONTROLLER (Gemini 2.5 Multi-Mode Polish)
  // ═══════════════════════════════════════════════════════════════════

  class AiPolishController {
    static currentTargetEl = null;
    static currentTargetText = '';
    static lastPolishedText = '';

    static init() {
      // 5 Quick 1-Click Enhancement Buttons
      const bindQuick = (id, mode) => {
        const btn = document.getElementById(id);
        if (btn) {
          btn.addEventListener('click', () => AiPolishController.runPolish(mode, '', btn));
        }
      };

      bindQuick('aiBtnMetrics', 'metrics');
      bindQuick('aiBtnVerbs', 'action_verbs');
      bindQuick('aiBtnAts', 'ats');
      bindQuick('aiBtnConcise', 'concise');
      bindQuick('aiBtnTone', 'tone');

      // Custom AI prompt button
      const btnCustom = document.getElementById('aiBtnRunCustom');
      const txtCustom = document.getElementById('aiCustomPrompt');
      if (btnCustom && txtCustom) {
        btnCustom.addEventListener('click', () => {
          const instruction = txtCustom.value.trim();
          if (!instruction) {
            alert('Please enter a custom instruction (e.g. "Focus on cloud deployment and cost reduction").');
            return;
          }
          AiPolishController.runPolish('custom', instruction, btnCustom);
        });
      }

      // Apply & Discard buttons
      document.getElementById('aiBtnApply')?.addEventListener('click', () => AiPolishController.applyPolish());
      document.getElementById('aiBtnDiscard')?.addEventListener('click', () => AiPolishController.discardPolish());
    }

    static setTarget(element, text) {
      this.currentTargetEl = element;
      this.currentTargetText = (text || (element ? element.innerText : '')).trim();
      const preview = document.getElementById('aiSelectedPreview');
      if (preview) {
        if (this.currentTargetText) {
          preview.innerText = `"${this.currentTargetText.slice(0, 140)}${this.currentTargetText.length > 140 ? '...' : ''}"`;
          preview.style.fontStyle = 'normal';
          preview.style.color = 'var(--editor-text)';
        } else {
          preview.innerText = 'Click any bullet or section on the artboard to target it.';
          preview.style.fontStyle = 'italic';
          preview.style.color = 'var(--editor-text-muted)';
        }
      }
    }

    static openAiStudioWithText(element, text) {
      // Switch sidebar to AI tab
      document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.sidebar-panel').forEach(p => p.classList.remove('active'));

      const aiTab = document.querySelector('.sidebar-tab[data-tab="ai"]');
      const aiPanel = document.getElementById('panelAi');
      if (aiTab) aiTab.classList.add('active');
      if (aiPanel) aiPanel.classList.add('active');

      if (element || text) {
        this.setTarget(element, text);
      }
    }

    static async runPolish(mode, customInstruction = '', btnEl = null) {
      if (!this.currentTargetText) {
        const firstBullet = document.querySelector('.bullet-item') || document.querySelector('.summary-text');
        if (firstBullet) {
          this.setTarget(firstBullet, firstBullet.innerText);
        } else {
          alert('Please click on a bullet or text on your resume to polish it.');
          return;
        }
      }

      const origBtnHtml = btnEl ? btnEl.innerHTML : '';
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Polishing with Gemini 2.5...';
      }

      const diffCard = document.getElementById('aiDiffCard');
      const diffText = document.getElementById('aiPolishedText');

      try {
        const config = window.EDITOR_CONFIG || {};
        const url = config.aiPolishUrl || '/api/editor/ai-polish';

        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: this.currentTargetText,
            mode: mode,
            instruction: customInstruction,
            target_role: store.state.resume?.target_role || ''
          })
        });

        const data = await resp.json();
        if (!data.success) {
          throw new Error(data.error || 'Failed to polish text with AI.');
        }

        this.lastPolishedText = data.polished;

        if (diffCard && diffText) {
          diffText.innerText = data.polished;
          diffCard.style.display = 'block';
          diffCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      } catch (err) {
        console.error('[AI Polish] Error:', err);
        alert('AI Polish Error: ' + err.message);
      } finally {
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.innerHTML = origBtnHtml;
        }
      }
    }

    static applyPolish() {
      if (!this.lastPolishedText || !this.currentTargetEl) return;

      this.currentTargetEl.innerText = this.lastPolishedText;
      InlineEditor.syncDomToResumeJson();
      store.pushSnapshot('AI Polish Applied');
      PageOverflowDetector.check();
      AutoSaver.trigger();

      this.setTarget(this.currentTargetEl, this.lastPolishedText);

      const diffCard = document.getElementById('aiDiffCard');
      if (diffCard) diffCard.style.display = 'none';

      InlineEditor.pulseBlock(this.currentTargetEl.closest('.editor-block') || this.currentTargetEl);
    }

    static discardPolish() {
      const diffCard = document.getElementById('aiDiffCard');
      if (diffCard) diffCard.style.display = 'none';
      this.lastPolishedText = '';
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 11. ZOOM CONTROLLER
  // ═══════════════════════════════════════════════════════════════════

  class ZoomController {
    static init() {
      const slider = document.getElementById('zoomSlider');
      const label = document.getElementById('zoomLabel');
      const btnIn = document.getElementById('btnZoomIn');
      const btnOut = document.getElementById('btnZoomOut');
      const btnFit = document.getElementById('btnZoomFit');

      if (!slider) return;

      const setZoom = (z) => {
        const clamped = Math.max(25, Math.min(400, z));
        slider.value = clamped;
        if (label) label.innerText = `${Math.round(clamped)}%`;
        store.state.zoom = clamped;

        const viewport = document.getElementById('editorViewport');
        if (viewport) {
          viewport.style.transform = `scale(${clamped / 100})`;
        }
      };

      slider.addEventListener('input', () => setZoom(slider.value));
      btnIn?.addEventListener('click', () => setZoom((parseInt(slider.value) || 100) + 15));
      btnOut?.addEventListener('click', () => setZoom((parseInt(slider.value) || 100) - 15));

      btnFit?.addEventListener('click', () => {
        const workspace = document.getElementById('editorWorkspace');
        const artboard = document.getElementById('editorArtboard');
        if (!workspace || !artboard) return;

        const availH = workspace.clientHeight - 80;
        const artH = artboard.offsetHeight || 1056;
        const fitRatio = Math.floor((availH / artH) * 100);
        setZoom(fitRatio);
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 12. DRAG MANAGER (Independent Section Drag with Insertion Guide)
  // ═══════════════════════════════════════════════════════════════════

  class DragManager {
    static init() {
      const container = document.getElementById('resumeContent');
      if (!container) return;

      let draggedEl = null;
      let dropIndicator = document.createElement('div');
      dropIndicator.className = 'block-drop-indicator';
      container.parentNode.appendChild(dropIndicator);

      container.addEventListener('dragstart', (e) => {
        const handle = e.target.closest('.block-drag-handle');
        if (!handle) return;

        draggedEl = handle.closest('.editor-block');
        if (!draggedEl) return;

        draggedEl.classList.add('dragging');
        e.dataTransfer.setData('text/plain', draggedEl.getAttribute('data-block-id'));
        e.dataTransfer.effectAllowed = 'move';
      });

      container.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        const targetBlock = e.target.closest('.editor-block');
        if (!targetBlock || targetBlock === draggedEl) {
          dropIndicator.classList.remove('visible');
          return;
        }

        const rect = targetBlock.getBoundingClientRect();
        const midY = rect.top + rect.height / 2;
        const insertBefore = e.clientY < midY;

        dropIndicator.style.width = `${rect.width}px`;
        dropIndicator.style.left = `${targetBlock.offsetLeft}px`;
        dropIndicator.style.top = `${insertBefore ? targetBlock.offsetTop - 2 : targetBlock.offsetTop + targetBlock.offsetHeight + 2}px`;
        dropIndicator.classList.add('visible');
        dropIndicator._target = targetBlock;
        dropIndicator._insertBefore = insertBefore;
      });

      container.addEventListener('dragleave', (e) => {
        if (!container.contains(e.relatedTarget)) {
          dropIndicator.classList.remove('visible');
        }
      });

      container.addEventListener('dragend', () => {
        if (draggedEl) draggedEl.classList.remove('dragging');
        draggedEl = null;
        dropIndicator.classList.remove('visible');
      });

      container.addEventListener('drop', (e) => {
        e.preventDefault();
        dropIndicator.classList.remove('visible');

        if (draggedEl && dropIndicator._target) {
          if (dropIndicator._insertBefore) {
            dropIndicator._target.parentNode.insertBefore(draggedEl, dropIndicator._target);
          } else {
            dropIndicator._target.parentNode.insertBefore(draggedEl, dropIndicator._target.nextSibling);
          }
          store.pushSnapshot('Reorder Section Blocks');
          PageOverflowDetector.check();
          AutoSaver.trigger();
        }
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 13. PAGE OVERFLOW DETECTOR & AUTO-FIT CONTROLLER
  // ═══════════════════════════════════════════════════════════════════

  class PageOverflowDetector {
    static check() {
      const artboard = document.getElementById('editorArtboard');
      const content = document.getElementById('resumeContent');
      const autoFitBtn = document.getElementById('btnAutoFit');
      const pageCounter = document.getElementById('pageCounter');
      if (!artboard || !content) return;

      const pageLimitPx = 1056; // Letter height at 96 DPI
      const contentH = content.offsetHeight;
      const totalPages = Math.max(1, Math.ceil(contentH / pageLimitPx));

      if (pageCounter) {
        pageCounter.innerText = `Page 1 of ${totalPages}`;
      }

      if (contentH > pageLimitPx + 15) {
        artboard.classList.add('content-overflow');
        if (autoFitBtn) autoFitBtn.style.display = 'flex';
      } else {
        artboard.classList.remove('content-overflow');
        if (autoFitBtn) autoFitBtn.style.display = 'none';
      }
    }

    static initAutoFit() {
      const btn = document.getElementById('btnAutoFit');
      if (!btn) return;

      btn.addEventListener('click', () => {
        const { typography, spacing } = store.state.styles;
        let pt = parseFloat(typography.fontSize) || 9.5;
        let secGap = parseFloat(spacing.sectionGap) || 6;
        let bulletGap = parseFloat(spacing.bulletGap) || 1;

        if (pt > 8.5) pt -= 0.5;
        if (secGap > 3) secGap -= 1;
        if (bulletGap > 0) bulletGap = 0;

        store.state.styles.typography.fontSize = `${pt}pt`;
        store.state.styles.spacing.sectionGap = `${secGap}px`;
        store.state.styles.spacing.bulletGap = `${bulletGap}px`;

        store.applyStylesToArtboard();
        store.pushSnapshot('Auto-fit to 1 Page');
        PageOverflowDetector.check();
        AutoSaver.trigger();
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 14. AUTO-SAVER (Background Persistence)
  // ═══════════════════════════════════════════════════════════════════

  class AutoSaver {
    static timer = null;
    static isSaving = false;

    static init() {
      // Auto-save every 5 seconds if dirty
      setInterval(() => {
        if (store.state.isDirty && !AutoSaver.isSaving) {
          AutoSaver.saveNow();
        }
      }, 5000);
    }

    static trigger() {
      store.state.isDirty = true;
      const statusEl = document.getElementById('saveStatus');
      if (statusEl) {
        statusEl.innerHTML = '<span class="dot" style="background:#f59e0b"></span><span>Saving...</span>';
      }

      clearTimeout(AutoSaver.timer);
      AutoSaver.timer = setTimeout(() => {
        AutoSaver.saveNow();
      }, 1500);
    }

    static async saveNow() {
      if (AutoSaver.isSaving) return;
      AutoSaver.isSaving = true;

      const config = window.EDITOR_CONFIG || {};
      const payload = {
        resume_path: config.resumePath || 'tailored_resume.json',
        resume: store.state.resume,
        editor_styles: store.state.styles
      };

      try {
        const resp = await fetch(config.saveUrl || '/api/editor/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        const data = await resp.json();
        if (data.success) {
          store.state.isDirty = false;
          const statusEl = document.getElementById('saveStatus');
          if (statusEl) {
            statusEl.innerHTML = '<span class="dot" style="background:#10b981"></span><span>Saved</span>';
          }
        }
      } catch (err) {
        console.warn('[AutoSaver] Save failed:', err);
      } finally {
        AutoSaver.isSaving = false;
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 15. PDF EXPORTER (1:1 Exact Client DOM Playwright Export)
  // ═══════════════════════════════════════════════════════════════════

  class PdfExporter {
    static init() {
      const btnDownload = document.getElementById('btnDownloadPdf');
      const btnPrint = document.getElementById('btnPrintNative');

      // 1. Instant Print / Save as PDF (0 seconds, uses native browser print dialog)
      if (btnPrint) {
        btnPrint.addEventListener('click', () => {
          InlineEditor.hideFloatingToolbar();
          window.print();
        });
      }

      if (!btnDownload) return;

      // 2. Playwright Headless Chromium Vector PDF (Fast 2-3s server render)
      btnDownload.addEventListener('click', async () => {
        InlineEditor.hideFloatingToolbar();
        InlineEditor.syncDomToResumeJson();

        // Clone #resumeContent and strip editor chrome before sending HTML
        const contentEl = document.getElementById('resumeContent');
        let rawHtml = '';
        if (contentEl) {
          const clone = contentEl.cloneNode(true);
          clone.querySelectorAll('.block-actions-bar, .block-drag-handle, .block-drop-indicator').forEach(el => el.remove());
          clone.querySelectorAll('[contenteditable]').forEach(el => el.removeAttribute('contenteditable'));
          rawHtml = clone.innerHTML;
        }

        const origHtml = btnDownload.innerHTML;
        let seconds = 0;
        btnDownload.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating PDF (<span id="pdfSec">0</span>s)...';
        btnDownload.disabled = true;

        const timer = setInterval(() => {
          seconds++;
          const secSpan = document.getElementById('pdfSec');
          if (secSpan) secSpan.innerText = seconds;
        }, 1000);

        const config = window.EDITOR_CONFIG || {};
        const payload = {
          resume_path: config.resumePath || 'tailored_resume.json',
          resume: store.state.resume,
          editor_styles: store.state.styles,
          html: rawHtml
        };

        try {
          const resp = await fetch(config.exportPdfUrl || '/api/editor/export-pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });

          if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.error || `Export failed with status ${resp.status}`);
          }

          const blob = await resp.blob();
          const candidateName = store.state.resume.name || 'Candidate';
          const filename = `${candidateName.replace(/[^a-zA-Z0-9_\-]/g, '_')}_Resume.pdf`;

          const downloadUrl = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.style.display = 'none';
          a.href = downloadUrl;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          window.URL.revokeObjectURL(downloadUrl);
          a.remove();
        } catch (err) {
          console.error('[PdfExporter] Failed:', err);
          alert(`PDF Generation Error: ${err.message}`);
        } finally {
          clearInterval(timer);
          btnDownload.innerHTML = origHtml;
          btnDownload.disabled = false;
        }
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 16. SHORTCUT MANAGER (Ctrl+Z, Ctrl+Y, Ctrl+S, Ctrl+P)
  // ═══════════════════════════════════════════════════════════════════

  class ShortcutManager {
    static init() {
      document.addEventListener('keydown', (e) => {
        const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
        const modKey = isMac ? e.metaKey : e.ctrlKey;

        if (modKey && e.key.toLowerCase() === 'z') {
          e.preventDefault();
          if (e.shiftKey) store.redo();
          else store.undo();
        } else if (modKey && e.key.toLowerCase() === 'y') {
          e.preventDefault();
          store.redo();
        } else if (modKey && e.key.toLowerCase() === 's') {
          e.preventDefault();
          AutoSaver.saveNow();
        }
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 17. BOOTSTRAP INITIALIZATION
  // ═══════════════════════════════════════════════════════════════════

  document.addEventListener('DOMContentLoaded', () => {
    let initialResume = {};
    const dataTag = document.getElementById('resumeData');
    if (dataTag && dataTag.textContent) {
      try {
        initialResume = JSON.parse(dataTag.textContent);
      } catch (err) {
        console.error('[Editor] Failed to parse injected JSON:', err);
      }
    }

    store.init(initialResume);
    BlockRenderer.renderAll(store.state.resume, store.state.styles);

    SelectionManager.init();
    InlineEditor.init();
    ToolbarController.init();
    SpacingPopoverController.init();
    ColorPopoverController.init();
    InspectorController.init();
    SidebarController.init();
    ZoomController.init();
    DragManager.init();
    PageOverflowDetector.initAutoFit();
    AutoSaver.init();
    PdfExporter.init();
    ShortcutManager.init();

    store.subscribe((event) => {
      if (event === 'state_restored') {
        BlockRenderer.renderAll(store.state.resume, store.state.styles);
      }
    });

    console.log('[Editor] Canva / Word Grade visual PDF resume editor engine loaded successfully.');
  });

})();
