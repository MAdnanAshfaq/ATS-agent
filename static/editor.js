/**
 * ==============================================================================
 * Canva-Grade Visual PDF Resume Editor — Core JavaScript Engine
 * ==============================================================================
 * 1:1 Pixel-Perfect DOM & PDF Parity, Block Selection, Inline Editing,
 * Typography/Spacing Live Sliders, Drag & Drop Reordering, Auto-Fit, and Auto-Save.
 * ==============================================================================
 */

(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════
  // 1. STATE STORE (Reactive, Undo/Redo Snapshots, CSS Variable Binding)
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
        isEditing: false,
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
      // Discard future history if we are in the middle of undo stack
      if (this.historyIndex < this.history.length - 1) {
        this.history = this.history.slice(0, this.historyIndex + 1);
      }

      const snapshot = {
        label,
        resume: JSON.parse(JSON.stringify(this.state.resume)),
        styles: JSON.parse(JSON.stringify(this.state.styles)),
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
      this.notify('undo_applied', snapshot);
      this.notify('state_restored', snapshot);
    }

    redo() {
      if (!this.canRedo()) return;
      this.historyIndex++;
      const snapshot = this.history[this.historyIndex];
      this.state.resume = JSON.parse(JSON.stringify(snapshot.resume));
      this.state.styles = JSON.parse(JSON.stringify(snapshot.styles));
      this.applyStylesToArtboard();
      this.notify('redo_applied', snapshot);
      this.notify('state_restored', snapshot);
    }

    updateStyle(category, key, value) {
      if (!this.state.styles[category]) {
        this.state.styles[category] = {};
      }
      this.state.styles[category][key] = value;
      this.applyStylesToArtboard();
      this.pushSnapshot(`Update ${category}.${key}`);
      this.notify('style_updated', { category, key, value });
    }

    applyStylesToArtboard() {
      const artboard = document.getElementById('editorArtboard');
      if (!artboard) return;

      const { typography, spacing, colors, page } = this.state.styles;

      // Font family mapping with safe fallbacks
      const font = typography.fontFamily || 'Carlito';
      artboard.style.setProperty('--resume-font', `'${font}', 'Calibri', 'Segoe UI', Arial, sans-serif`);

      // Sizes & typography
      artboard.style.setProperty('--resume-base-size', typography.fontSize || '9.5pt');
      artboard.style.setProperty('--resume-line-height', typography.lineHeight || '1.22');
      artboard.style.setProperty('--resume-letter-spacing', typography.letterSpacing || '0px');

      // Gaps
      artboard.style.setProperty('--resume-section-gap', spacing.sectionGap || '6px');
      artboard.style.setProperty('--resume-entry-gap', spacing.entryGap || '4px');
      artboard.style.setProperty('--resume-bullet-gap', spacing.bulletGap || '1px');

      // Colors
      artboard.style.setProperty('--resume-text-color', colors.text || '#000000');
      artboard.style.setProperty('--resume-border-color', colors.border || '#111827');
      artboard.style.setProperty('--resume-link-color', colors.link || '#1a56db');

      // Margins
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
      this.state.isEditing = false;
      this.notify('selection_cleared');
    }

    setEditing(isEditing) {
      this.state.isEditing = isEditing;
      this.notify('editing_state_changed', { isEditing });
    }
  }

  // Instantiate singleton store
  const store = new EditorStore();


  // ═══════════════════════════════════════════════════════════════════
  // 2. BLOCK RENDERER (Turns JSON into Editable DOM with 1:1 Parity)
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

      // Re-apply block selection if previously selected
      if (store.state.selectedBlockId) {
        const sel = container.querySelector(`[data-block-id="${store.state.selectedBlockId}"]`);
        if (sel) sel.classList.add('selected');
      }

      // Check overflow after render
      setTimeout(() => PageOverflowDetector.check(), 50);
    }

    static createBlockWrapper(blockId, blockType) {
      const wrapper = document.createElement('div');
      wrapper.className = 'editor-block';
      wrapper.setAttribute('data-block-id', blockId);
      wrapper.setAttribute('data-block-type', blockType);

      // Drag handle
      const handle = document.createElement('div');
      handle.className = 'block-drag-handle';
      handle.title = 'Drag to reorder';
      handle.innerHTML = '<i class="fa-solid fa-grip-vertical"></i>';
      wrapper.appendChild(handle);

      return wrapper;
    }

    static renderHeader(resume) {
      const block = BlockRenderer.createBlockWrapper('header', 'header');

      const headerDiv = document.createElement('div');
      headerDiv.className = 'resume-header';

      const name = resume.name || 'Candidate Name';
      const role = resume.target_role || '';
      const contact = resume.contact || {};

      let html = `<div class="candidate-name" data-edit="name">${BlockRenderer.escapeHtml(name.toUpperCase())}</div>`;
      if (role) {
        html += `<div class="target-role" data-edit="target_role">${BlockRenderer.escapeHtml(role)}</div>`;
      }

      const parts = [];
      if (contact.email) parts.push(`<a href="mailto:${BlockRenderer.escapeHtml(contact.email)}" data-edit="contact-email">${BlockRenderer.escapeHtml(contact.email)}</a>`);
      if (contact.phone) parts.push(`<a href="tel:${BlockRenderer.escapeHtml(contact.phone)}" data-edit="contact-phone">${BlockRenderer.escapeHtml(contact.phone)}</a>`);
      if (contact.location) parts.push(`<span data-edit="contact-location">${BlockRenderer.escapeHtml(contact.location)}</span>`);
      if (contact.linkedin) {
        const url = contact.linkedin.startsWith('http') ? contact.linkedin : `https://${contact.linkedin}`;
        parts.push(`<a href="${BlockRenderer.escapeHtml(url)}" target="_blank" data-edit="contact-linkedin">${BlockRenderer.escapeHtml(contact.linkedin)}</a>`);
      }
      if (contact.github) {
        const url = contact.github.startsWith('http') ? contact.github : `https://${contact.github}`;
        parts.push(`<a href="${BlockRenderer.escapeHtml(url)}" target="_blank" data-edit="contact-github">${BlockRenderer.escapeHtml(contact.github)}</a>`);
      }
      if (contact.portfolio) {
        const url = contact.portfolio.startsWith('http') ? contact.portfolio : `https://${contact.portfolio}`;
        parts.push(`<a href="${BlockRenderer.escapeHtml(url)}" target="_blank" data-edit="contact-portfolio">${BlockRenderer.escapeHtml(contact.portfolio)}</a>`);
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
            <div class="section-title" data-edit="section-heading" data-section="summary">${BlockRenderer.escapeHtml(title)}</div>
            <p class="summary-text" data-edit="summary">${BlockRenderer.escapeHtml(resume.summary)}</p>
          `;
          return block;
        }

        case 'skills': {
          const skills = resume.skills || [];
          if (!skills || skills.length === 0) return null;
          const block = BlockRenderer.createBlockWrapper('section-skills', 'skills');
          const title = headings.skills || 'Technical Skills';
          let body = `<div class="section-title" data-edit="section-heading" data-section="skills">${BlockRenderer.escapeHtml(title)}</div>`;

          // Skills categorization
          const categorized = BlockRenderer.categorizeSkills(skills);
          for (const [catName, catItems] of Object.entries(categorized)) {
            if (catItems && catItems.length > 0) {
              body += `
                <div class="skill-category" data-cat="${BlockRenderer.escapeHtml(catName)}">
                  <span class="skill-category-label" data-edit="skill-cat-label">${BlockRenderer.escapeHtml(catName)}:</span>
                  <span class="skill-category-list" data-edit="skills-list">${BlockRenderer.escapeHtml(catItems.join(', '))}</span>
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
          titleBlock.innerHTML += `<div class="section-title" data-edit="section-heading" data-section="experience">${BlockRenderer.escapeHtml(title)}</div>`;
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
                  <span class="two-col-left role-title" data-edit="exp-title">${BlockRenderer.escapeHtml(roleTitle)}</span>
                  ${dates ? `<span class="two-col-right role-dates" data-edit="exp-dates">${BlockRenderer.escapeHtml(dates)}</span>` : ''}
                </div>
                ${company || loc ? `
                  <div class="sub-line">
                    <span class="sub-left role-company" data-edit="exp-company">${BlockRenderer.escapeHtml(company)}</span>
                    ${loc ? `<span class="sub-right role-location" data-edit="exp-loc">${BlockRenderer.escapeHtml(loc)}</span>` : ''}
                  </div>
                ` : ''}
            `;

            if (bullets.length > 0) {
              entryHtml += `<ul class="bullet-list" data-edit="bullet-list">`;
              bullets.forEach(b => {
                if (b && String(b).trim().length > 0) {
                  entryHtml += `<li class="bullet-item" data-edit="bullet">${BlockRenderer.escapeHtml(b)}</li>`;
                }
              });
              entryHtml += `</ul>`;
            }
            entryHtml += `</div>`;

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
          let body = `<div class="section-title" data-edit="section-heading" data-section="education">${BlockRenderer.escapeHtml(title)}</div>`;

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
                  <span class="two-col-left" data-edit="edu-degree">${BlockRenderer.escapeHtml(degTitle)}</span>
                  ${gdate ? `<span class="two-col-right" data-edit="edu-date">${BlockRenderer.escapeHtml(gdate)}</span>` : ''}
                </div>
                ${inst && degTitle !== inst ? `
                  <div class="sub-line"><span class="sub-left" data-edit="edu-school">${BlockRenderer.escapeHtml(inst)}</span></div>
                ` : ''}
                ${gpa ? `<div class="gpa-line" data-edit="edu-gpa">GPA: ${BlockRenderer.escapeHtml(gpa)}</div>` : ''}
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
          let body = `<div class="section-title" data-edit="section-heading" data-section="certifications">${BlockRenderer.escapeHtml(title)}</div><ul class="bullet-list">`;
          certs.forEach(c => {
            if (c) body += `<li class="bullet-item" data-edit="bullet">${BlockRenderer.escapeHtml(c)}</li>`;
          });
          body += `</ul>`;
          block.innerHTML += body;
          return block;
        }

        case 'projects': {
          const projList = resume.projects || [];
          if (!projList || projList.length === 0) return null;
          const block = BlockRenderer.createBlockWrapper('section-projects', 'projects');
          const title = headings.projects || 'Key Projects';
          let body = `<div class="section-title" data-edit="section-heading" data-section="projects">${BlockRenderer.escapeHtml(title)}</div>`;
          projList.forEach(p => {
            const pname = p.name || '';
            const pdesc = p.description || '';
            const pbullets = p.bullets || [];
            body += `
              <div class="entry-item">
                <div class="two-col-left" data-edit="proj-name">${BlockRenderer.escapeHtml(pname)}</div>
                ${pdesc ? `<p class="summary-text" data-edit="proj-desc" style="margin-bottom:2px;">${BlockRenderer.escapeHtml(pdesc)}</p>` : ''}
            `;
            if (pbullets.length > 0) {
              body += `<ul class="bullet-list">`;
              pbullets.forEach(b => {
                if (b) body += `<li class="bullet-item" data-edit="bullet">${BlockRenderer.escapeHtml(b)}</li>`;
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
      if (typeof skills === 'object' && !Array.isArray(skills)) {
        return skills;
      }

      const categories = {
        'Languages': [],
        'Frameworks & Libraries': [],
        'Tools & Platforms': [],
        'Core Competencies': []
      };

      const langRegex = /\b(python|javascript|typescript|java|c\+\+|c#|ruby|go|golang|rust|php|swift|kotlin|sql|bash|html|css)\b/i;
      const frameworkRegex = /\b(react|vue|angular|node|express|django|flask|fastapi|spring|rails|next\.?js|laravel|asp\.net)\b/i;
      const toolRegex = /\b(docker|kubernetes|aws|azure|gcp|git|github|ci\/cd|terraform|linux|jenkins|jira|postman|graphql|rest)\b/i;

      skills.forEach(s => {
        const str = String(s).trim();
        if (!str) return;
        if (langRegex.test(str)) {
          categories['Languages'].push(str);
        } else if (frameworkRegex.test(str)) {
          categories['Frameworks & Libraries'].push(str);
        } else if (toolRegex.test(str)) {
          categories['Tools & Platforms'].push(str);
        } else {
          categories['Core Competencies'].push(str);
        }
      });

      // Filter empty
      const res = {};
      for (const [k, v] of Object.entries(categories)) {
        if (v.length > 0) res[k] = v;
      }
      return Object.keys(res).length > 0 ? res : { 'Skills': skills };
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 3. SELECTION MANAGER (Block Select, Deselect, Multi-Block Focus)
  // ═══════════════════════════════════════════════════════════════════

  class SelectionManager {
    static init() {
      const artboard = document.getElementById('editorArtboard');
      if (!artboard) return;

      artboard.addEventListener('click', (e) => {
        // If we are currently inline editing, don't trigger block selection unless clicking a different block
        const block = e.target.closest('.editor-block');
        if (!block) {
          if (!e.target.closest('.floating-toolbar')) {
            SelectionManager.clearSelection();
          }
          return;
        }

        const blockId = block.getAttribute('data-block-id');
        if (store.state.selectedBlockId !== blockId) {
          SelectionManager.selectBlock(block);
        }
      });

      // Clicking outside artboard clears selection (unless clicking toolbar/panel)
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
      const firstTarget = blockEl.querySelector('.bullet-item, .summary-text, .section-title, .role-title');
      if (firstTarget && typeof AiPolishController !== 'undefined') {
        AiPolishController.setTarget(firstTarget, firstTarget.innerText);
      }
    }

    static clearSelection() {
      document.querySelectorAll('.editor-block.selected').forEach(el => el.classList.remove('selected'));
      InlineEditor.stopEditing();
      store.clearSelection();
      InspectorController.showEmpty();
      if (typeof AiPolishController !== 'undefined') {
        AiPolishController.setTarget(null, '');
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 4. INLINE TEXT EDITOR (Double-Click ContentEditable, Floating Toolbar)
  // ═══════════════════════════════════════════════════════════════════

  class InlineEditor {
    static init() {
      const artboard = document.getElementById('editorArtboard');
      if (!artboard) return;

      // Double-click to start inline editing
      artboard.addEventListener('dblclick', (e) => {
        const editableTarget = e.target.closest('[data-edit]') || e.target.closest('.editor-block');
        if (editableTarget) {
          InlineEditor.startEditing(editableTarget);
        }
      });

      // Floating toolbar actions
      const floatBar = document.getElementById('floatingToolbar');
      if (floatBar) {
        floatBar.addEventListener('click', (e) => {
          const btn = e.target.closest('.toolbar-btn');
          if (!btn) return;
          const cmd = btn.getAttribute('data-cmd');
          if (cmd) {
            document.execCommand(cmd, false, null);
            InlineEditor.updateFloatingToolbarPos();
          }
        });
      }
    }

    static startEditing(element) {
      const block = element.closest('.editor-block');
      if (!block) return;

      SelectionManager.selectBlock(block);
      block.classList.add('editing');
      store.setEditing(true);

      // Make element editable
      element.setAttribute('contenteditable', 'true');
      element.focus();

      if (typeof AiPolishController !== 'undefined') {
        AiPolishController.setTarget(element, element.innerText);
      }

      // Clean paste event to prevent styled HTML garbage
      element.onpaste = (e) => {
        e.preventDefault();
        const text = (e.clipboardData || window.clipboardData).getData('text/plain');
        document.execCommand('insertText', false, text);
      };

      // Show floating toolbar above the active target
      InlineEditor.activeElement = element;
      InlineEditor.updateFloatingToolbarPos();

      // Handle blur & Escape
      element.onblur = () => {
        setTimeout(() => {
          // If clicked into floating toolbar, don't stop
          if (document.activeElement && document.activeElement.closest('#floatingToolbar')) {
            return;
          }
          InlineEditor.commitEdits(element, block);
        }, 120);
      };

      element.onkeydown = (e) => {
        if (e.key === 'Escape') {
          element.blur();
        } else if (e.key === 'Enter' && element.getAttribute('data-edit') === 'bullet') {
          // Normal list enter behavior
        }
      };
    }

    static updateFloatingToolbarPos() {
      const bar = document.getElementById('floatingToolbar');
      if (!bar || !InlineEditor.activeElement) return;

      const rect = InlineEditor.activeElement.getBoundingClientRect();
      const barH = 38;
      let top = rect.top - barH - 8;
      let left = rect.left + (rect.width / 2) - 100;

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

    static commitEdits(element, block) {
      element.removeAttribute('contenteditable');
      block.classList.remove('editing');
      InlineEditor.hideFloatingToolbar();
      InlineEditor.activeElement = null;
      store.setEditing(false);

      // Scrape updated text back into store.state.resume
      InlineEditor.syncDomToResumeJson();
      store.pushSnapshot('Inline Edit');
      PageOverflowDetector.check();
      AutoSaver.trigger();
    }

    static stopEditing() {
      if (InlineEditor.activeElement) {
        InlineEditor.activeElement.blur();
      }
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

      // Contact
      if (!r.contact) r.contact = {};
      const em = getTxt('[data-edit="contact-email"]');
      if (em) r.contact.email = em;
      const ph = getTxt('[data-edit="contact-phone"]');
      if (ph) r.contact.phone = ph;
      const loc = getTxt('[data-edit="contact-location"]');
      if (loc) r.contact.location = loc;

      // Summary
      const summary = getTxt('.summary-text[data-edit="summary"]');
      if (summary) r.summary = summary;

      // Experience entries
      const expBlocks = document.querySelectorAll('.editor-block[data-block-type="experience-entry"]');
      if (expBlocks.length > 0 && Array.isArray(r.experience)) {
        expBlocks.forEach((eb, idx) => {
          if (r.experience[idx]) {
            const title = eb.querySelector('[data-edit="exp-title"]');
            if (title) r.experience[idx].title = title.innerText.trim();
            const comp = eb.querySelector('[data-edit="exp-company"]');
            if (comp) r.experience[idx].company = comp.innerText.trim();
            const dt = eb.querySelector('[data-edit="exp-dates"]');
            if (dt) r.experience[idx].dates = dt.innerText.trim();
            const locEl = eb.querySelector('[data-edit="exp-loc"]');
            if (locEl) r.experience[idx].location = locEl.innerText.trim();

            const bullets = [];
            eb.querySelectorAll('.bullet-item[data-edit="bullet"]').forEach(li => {
              const bText = li.innerText.trim();
              if (bText) bullets.push(bText);
            });
            if (bullets.length > 0) r.experience[idx].bullets = bullets;
          }
        });
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 5. TOOLBAR CONTROLLER (Top Bar Font, Size, Styles, Alignment)
  // ═══════════════════════════════════════════════════════════════════

  class ToolbarController {
    static init() {
      // Back button
      const btnBack = document.getElementById('btnBack');
      if (btnBack) {
        btnBack.addEventListener('click', () => {
          if (window.EDITOR_CONFIG && window.EDITOR_CONFIG.backUrl) {
            window.location.href = window.EDITOR_CONFIG.backUrl;
          } else {
            window.history.back();
          }
        });
      }

      // Font Family
      const fontSelect = document.getElementById('fontFamilySelect');
      if (fontSelect) {
        fontSelect.value = store.state.styles.typography.fontFamily || 'Carlito';
        fontSelect.addEventListener('change', (e) => {
          store.updateStyle('typography', 'fontFamily', e.target.value);
        });
      }

      // Font Size Stepper
      const sizeInput = document.getElementById('fontSizeInput');
      const btnSizeDec = document.getElementById('btnSizeDec');
      const btnSizeInc = document.getElementById('btnSizeInc');

      if (sizeInput) {
        const currentPt = parseFloat(store.state.styles.typography.fontSize) || 9.5;
        sizeInput.value = currentPt;

        sizeInput.addEventListener('change', () => {
          const val = `${parseFloat(sizeInput.value) || 9.5}pt`;
          store.updateStyle('typography', 'fontSize', val);
        });

        if (btnSizeDec) {
          btnSizeDec.addEventListener('click', () => {
            let val = (parseFloat(sizeInput.value) || 9.5) - 0.5;
            if (val < 6) val = 6;
            sizeInput.value = val;
            store.updateStyle('typography', 'fontSize', `${val}pt`);
          });
        }

        if (btnSizeInc) {
          btnSizeInc.addEventListener('click', () => {
            let val = (parseFloat(sizeInput.value) || 9.5) + 0.5;
            if (val > 28) val = 28;
            sizeInput.value = val;
            store.updateStyle('typography', 'fontSize', `${val}pt`);
          });
        }
      }

      // Formatting: Bold, Italic, Underline, Strikethrough
      const bindExec = (id, cmd) => {
        const btn = document.getElementById(id);
        if (btn) {
          btn.addEventListener('click', () => {
            document.execCommand(cmd, false, null);
          });
        }
      };
      bindExec('btnBold', 'bold');
      bindExec('btnItalic', 'italic');
      bindExec('btnUnderline', 'underline');
      bindExec('btnStrike', 'strikeThrough');

      // Alignment
      bindExec('btnAlignLeft', 'justifyLeft');
      bindExec('btnAlignCenter', 'justifyCenter');
      bindExec('btnAlignRight', 'justifyRight');
      bindExec('btnAlignJustify', 'justifyFull');

      // Lists
      bindExec('btnBulletList', 'insertUnorderedList');
      bindExec('btnOrderedList', 'insertOrderedList');

      // Case cycling (UPPERCASE -> lowercase -> Title Case)
      const btnCase = document.getElementById('btnCase');
      if (btnCase) {
        btnCase.addEventListener('click', () => {
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
        });
      }

      // Undo / Redo buttons
      const btnUndo = document.getElementById('btnUndo');
      const btnRedo = document.getElementById('btnRedo');
      if (btnUndo) btnUndo.addEventListener('click', () => store.undo());
      if (btnRedo) btnRedo.addEventListener('click', () => store.redo());

      // Update undo/redo button disabled appearance
      store.subscribe((event) => {
        if (event === 'history_change' || event === 'undo_applied' || event === 'redo_applied') {
          if (btnUndo) btnUndo.style.opacity = store.canUndo() ? '1' : '0.4';
          if (btnRedo) btnRedo.style.opacity = store.canRedo() ? '1' : '0.4';
        }
      });

      // Spacing Popover toggle
      const btnSpacing = document.getElementById('btnSpacing');
      const spacingPopover = document.getElementById('spacingPopover');
      if (btnSpacing && spacingPopover) {
        btnSpacing.addEventListener('click', (e) => {
          e.stopPropagation();
          const isVis = spacingPopover.classList.contains('visible');
          ColorPopoverController.hide();
          if (isVis) {
            spacingPopover.classList.remove('visible');
          } else {
            const rect = btnSpacing.getBoundingClientRect();
            spacingPopover.style.top = `${rect.bottom + 6}px`;
            spacingPopover.style.left = `${rect.left}px`;
            spacingPopover.classList.add('visible');
          }
        });
      }

      // Color Popover toggle
      const btnColor = document.getElementById('btnTextColor');
      const colorPopover = document.getElementById('colorPopover');
      if (btnColor && colorPopover) {
        btnColor.addEventListener('click', (e) => {
          e.stopPropagation();
          const isVis = colorPopover.classList.contains('visible');
          SpacingPopoverController.hide();
          if (isVis) {
            colorPopover.classList.remove('visible');
          } else {
            const rect = btnColor.getBoundingClientRect();
            colorPopover.style.top = `${rect.bottom + 6}px`;
            colorPopover.style.left = `${rect.left}px`;
            colorPopover.classList.add('visible');
          }
        });
      }

      // Clicking anywhere outside hides popovers
      document.addEventListener('click', (e) => {
        if (!e.target.closest('#spacingPopover') && !e.target.closest('#btnSpacing')) {
          SpacingPopoverController.hide();
        }
        if (!e.target.closest('#colorPopover') && !e.target.closest('#btnTextColor')) {
          ColorPopoverController.hide();
        }
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 6. SPACING POPOVER CONTROLLER (Live Line-Height, Gaps, Letter-Space)
  // ═══════════════════════════════════════════════════════════════════

  class SpacingPopoverController {
    static init() {
      // Line Height (min 80, max 250 -> 0.8 to 2.50)
      const sLh = document.getElementById('sliderLineHeight');
      const vLh = document.getElementById('valLineHeight');
      if (sLh && vLh) {
        sLh.value = Math.round((parseFloat(store.state.styles.typography.lineHeight) || 1.22) * 100);
        vLh.innerText = (sLh.value / 100).toFixed(2);
        sLh.addEventListener('input', () => {
          const val = (sLh.value / 100).toFixed(2);
          vLh.innerText = val;
          store.updateStyle('typography', 'lineHeight', val);
        });
      }

      // Letter Spacing (-200 to 600 -> -0.2px to 0.6px)
      const sLs = document.getElementById('sliderLetterSpacing');
      const vLs = document.getElementById('valLetterSpacing');
      if (sLs && vLs) {
        sLs.addEventListener('input', () => {
          const pxVal = (sLs.value / 1000).toFixed(2);
          vLs.innerText = `${pxVal}px`;
          store.updateStyle('typography', 'letterSpacing', `${pxVal}px`);
        });
      }

      // Section Gap (0 to 20px)
      const sSg = document.getElementById('sliderSectionGap');
      const vSg = document.getElementById('valSectionGap');
      if (sSg && vSg) {
        sSg.value = parseInt(store.state.styles.spacing.sectionGap) || 6;
        vSg.innerText = `${sSg.value}px`;
        sSg.addEventListener('input', () => {
          vSg.innerText = `${sSg.value}px`;
          store.updateStyle('spacing', 'sectionGap', `${sSg.value}px`);
        });
      }

      // Entry Gap (0 to 16px)
      const sEg = document.getElementById('sliderEntryGap');
      const vEg = document.getElementById('valEntryGap');
      if (sEg && vEg) {
        sEg.value = parseInt(store.state.styles.spacing.entryGap) || 4;
        vEg.innerText = `${sEg.value}px`;
        sEg.addEventListener('input', () => {
          vEg.innerText = `${sEg.value}px`;
          store.updateStyle('spacing', 'entryGap', `${sEg.value}px`);
        });
      }

      // Bullet Gap (0 to 8px)
      const sBg = document.getElementById('sliderBulletGap');
      const vBg = document.getElementById('valBulletGap');
      if (sBg && vBg) {
        sBg.value = parseInt(store.state.styles.spacing.bulletGap) || 1;
        vBg.innerText = `${sBg.value}px`;
        sBg.addEventListener('input', () => {
          vBg.innerText = `${sBg.value}px`;
          store.updateStyle('spacing', 'bulletGap', `${sBg.value}px`);
        });
      }

      // Reset Defaults
      const btnReset = document.getElementById('btnSpacingReset');
      if (btnReset) {
        btnReset.addEventListener('click', () => {
          if (sLh) { sLh.value = 122; vLh.innerText = '1.22'; store.updateStyle('typography', 'lineHeight', '1.22'); }
          if (sLs) { sLs.value = 0; vLs.innerText = '0px'; store.updateStyle('typography', 'letterSpacing', '0px'); }
          if (sSg) { sSg.value = 6; vSg.innerText = '6px'; store.updateStyle('spacing', 'sectionGap', '6px'); }
          if (sEg) { sEg.value = 4; vEg.innerText = '4px'; store.updateStyle('spacing', 'entryGap', '4px'); }
          if (sBg) { sBg.value = 1; vBg.innerText = '1px'; store.updateStyle('spacing', 'bulletGap', '1px'); }
        });
      }
    }

    static hide() {
      const p = document.getElementById('spacingPopover');
      if (p) p.classList.remove('visible');
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 7. COLOR POPOVER CONTROLLER (Presets + Hex Input)
  // ═══════════════════════════════════════════════════════════════════

  class ColorPopoverController {
    static init() {
      const grid = document.getElementById('colorPresetGrid');
      const hexInput = document.getElementById('colorHexInput');
      const swatch = document.getElementById('colorSwatch');

      const presets = [
        '#000000', '#111827', '#1f2937', '#374151',
        '#1e3a8a', '#1d4ed8', '#0284c7', '#0f766e',
        '#15803d', '#b45309', '#b91c1c', '#4c1d95'
      ];

      if (grid) {
        grid.innerHTML = '';
        presets.forEach(color => {
          const item = document.createElement('div');
          item.className = 'color-preset';
          item.style.background = color;
          item.title = color;
          item.addEventListener('click', () => {
            ColorPopoverController.applyColor(color);
          });
          grid.appendChild(item);
        });
      }

      if (hexInput) {
        hexInput.addEventListener('change', () => {
          let c = hexInput.value.trim();
          if (!c.startsWith('#')) c = `#${c}`;
          ColorPopoverController.applyColor(c);
        });
      }
    }

    static applyColor(color) {
      const hexInput = document.getElementById('colorHexInput');
      const swatch = document.getElementById('colorSwatch');
      if (hexInput) hexInput.value = color;
      if (swatch) swatch.style.background = color;

      // Apply to text color in store
      store.updateStyle('colors', 'text', color);
      document.execCommand('foreColor', false, color);
    }

    static hide() {
      const p = document.getElementById('colorPopover');
      if (p) p.classList.remove('visible');
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 8. RIGHT INSPECTOR CONTROLLER (Typography, Layout, Actions)
  // ═══════════════════════════════════════════════════════════════════

  class InspectorController {
    static init() {
      // Section toggling (collapsible headers)
      document.querySelectorAll('.inspector-section-header').forEach(header => {
        header.addEventListener('click', () => {
          header.parentElement.classList.toggle('collapsed');
        });
      });

      // Close inspector
      const btnClose = document.getElementById('btnCloseInspector');
      if (btnClose) {
        btnClose.addEventListener('click', () => {
          SelectionManager.clearSelection();
        });
      }

      // Actions: Move Up, Down, Duplicate, Delete
      const btnUp = document.getElementById('inspMoveUp');
      const btnDown = document.getElementById('inspMoveDown');
      const btnDup = document.getElementById('inspDuplicate');
      const btnDel = document.getElementById('inspDelete');

      if (btnUp) btnUp.addEventListener('click', () => InspectorController.moveSelectedBlock(-1));
      if (btnDown) btnDown.addEventListener('click', () => InspectorController.moveSelectedBlock(1));
      if (btnDup) btnDup.addEventListener('click', () => InspectorController.duplicateSelectedBlock());
      if (btnDel) btnDel.addEventListener('click', () => InspectorController.deleteSelectedBlock());

      // Color pickers in inspector
      const inspTxtColor = document.getElementById('inspTextColor');
      const inspTxtSwatch = document.getElementById('inspTextColorSwatch');
      if (inspTxtColor) {
        inspTxtColor.addEventListener('change', () => {
          const col = inspTxtColor.value.trim();
          if (inspTxtSwatch) inspTxtSwatch.style.background = col;
          store.updateStyle('colors', 'text', col);
        });
      }

      const inspBorderColor = document.getElementById('inspBorderColor');
      const inspBorderSwatch = document.getElementById('inspBorderColorSwatch');
      if (inspBorderColor) {
        inspBorderColor.addEventListener('change', () => {
          const col = inspBorderColor.value.trim();
          if (inspBorderSwatch) inspBorderSwatch.style.background = col;
          store.updateStyle('colors', 'border', col);
        });
      }
    }

    static syncWithSelectedBlock(blockEl) {
      const empty = document.getElementById('inspectorEmpty');
      const content = document.getElementById('inspectorContent');
      const title = document.getElementById('inspectorTitle');

      if (empty) empty.style.display = 'none';
      if (content) content.style.display = 'block';

      const blockType = blockEl.getAttribute('data-block-type') || 'block';
      const blockId = blockEl.getAttribute('data-block-id') || '';

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

      if (title) title.innerText = titles[blockType] || 'Block Properties';

      // Sync form values
      const inspFont = document.getElementById('inspFontFamily');
      if (inspFont) inspFont.value = store.state.styles.typography.fontFamily || 'Carlito';

      const inspSize = document.getElementById('inspFontSize');
      if (inspSize) inspSize.value = parseFloat(store.state.styles.typography.fontSize) || 9.5;

      const inspLh = document.getElementById('inspLineHeight');
      if (inspLh) inspLh.value = parseFloat(store.state.styles.typography.lineHeight) || 1.22;
    }

    static showEmpty() {
      const empty = document.getElementById('inspectorEmpty');
      const content = document.getElementById('inspectorContent');
      if (empty) empty.style.display = 'block';
      if (content) content.style.display = 'none';
    }

    static moveSelectedBlock(direction) {
      const blockId = store.state.selectedBlockId;
      if (!blockId) return;

      const blockEl = document.querySelector(`[data-block-id="${blockId}"]`);
      if (!blockEl) return;

      if (direction === -1 && blockEl.previousElementSibling) {
        blockEl.parentNode.insertBefore(blockEl, blockEl.previousElementSibling);
        store.pushSnapshot('Move Block Up');
      } else if (direction === 1 && blockEl.nextElementSibling) {
        blockEl.parentNode.insertBefore(blockEl.nextElementSibling, blockEl);
        store.pushSnapshot('Move Block Down');
      }
    }

    static duplicateSelectedBlock() {
      const blockId = store.state.selectedBlockId;
      if (!blockId) return;
      const blockEl = document.querySelector(`[data-block-id="${blockId}"]`);
      if (!blockEl) return;

      const clone = blockEl.cloneNode(true);
      clone.setAttribute('data-block-id', `${blockId}-copy-${Date.now()}`);
      blockEl.parentNode.insertBefore(clone, blockEl.nextElementSibling);
      SelectionManager.selectBlock(clone);
      store.pushSnapshot('Duplicate Block');
    }

    static deleteSelectedBlock() {
      const blockId = store.state.selectedBlockId;
      if (!blockId) return;
      const blockEl = document.querySelector(`[data-block-id="${blockId}"]`);
      if (!blockEl) return;

      if (confirm('Delete this resume section/entry?')) {
        blockEl.remove();
        SelectionManager.clearSelection();
        store.pushSnapshot('Delete Block');
        PageOverflowDetector.check();
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 9. LEFT SIDEBAR CONTROLLER (Tabs, Add Sections, Templates, AI)
  // ═══════════════════════════════════════════════════════════════════

  class SidebarController {
    static init() {
      // Tab switching: sections, design, ai
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

      // Add Section buttons
      document.querySelectorAll('.sidebar-add-btn[data-add]').forEach(btn => {
        btn.addEventListener('click', () => {
          const type = btn.getAttribute('data-add');
          SidebarController.handleAddSection(type);
        });
      });

      // Template Presets
      document.querySelectorAll('.template-card').forEach(card => {
        card.addEventListener('click', () => {
          document.querySelectorAll('.template-card').forEach(c => c.classList.remove('active'));
          card.classList.add('active');
          const tpl = card.getAttribute('data-template');
          SidebarController.applyTemplate(tpl);
        });
      });

      // AI Tools
      SidebarController.initAiTools();
    }

    static handleAddSection(type) {
      const r = store.state.resume;
      if (type === 'experience') {
        if (!r.experience) r.experience = [];
        r.experience.unshift({
          title: 'Senior Professional',
          company: 'Leading Enterprise Inc.',
          dates: 'Jan 2023 - Present',
          location: 'New York, NY',
          bullets: [
            'Spearheaded key architecture overhaul boosting process throughput by 35%.',
            'Collaborated with cross-functional teams to deliver enterprise milestones ahead of schedule.'
          ]
        });
      } else if (type === 'education') {
        if (!r.education) r.education = [];
        r.education.push({
          institution: 'State University',
          degree: 'Bachelor of Science',
          field: 'Computer Science',
          graduation_date: '2022',
          gpa: '3.8'
        });
      } else if (type === 'skill') {
        if (!r.skills) r.skills = [];
        r.skills.push('Cloud Architecture', 'System Design', 'Agile Leadership');
      } else if (type === 'certification') {
        if (!r.certifications) r.certifications = [];
        r.certifications.push('AWS Certified Solutions Architect — Associate (2024)');
      } else if (type === 'project') {
        if (!r.projects) r.projects = [];
        r.projects.push({
          name: 'Distributed Scalable Pipeline',
          description: 'High-throughput event streaming platform processing 10M+ daily events.',
          bullets: ['Reduced processing latency by 40% using Kafka & Redis caching.']
        });
      } else if (type === 'summary') {
        if (!r.summary) {
          r.summary = 'Strategic and results-driven professional with deep expertise in designing scalable architectures, leading high-performance engineering initiatives, and delivering impactful enterprise results.';
        }
      }

      BlockRenderer.renderAll(r, store.state.styles);
      store.pushSnapshot(`Add ${type}`);
    }

    static applyTemplate(templateName) {
      switch (templateName) {
        case 'ats-classic':
          store.updateStyle('typography', 'fontFamily', 'Carlito');
          store.updateStyle('typography', 'fontSize', '9.5pt');
          store.updateStyle('typography', 'lineHeight', '1.22');
          store.updateStyle('spacing', 'sectionGap', '6px');
          store.updateStyle('spacing', 'entryGap', '4px');
          store.updateStyle('colors', 'text', '#000000');
          store.updateStyle('colors', 'border', '#111827');
          break;

        case 'executive':
          store.updateStyle('typography', 'fontFamily', 'Georgia');
          store.updateStyle('typography', 'fontSize', '10pt');
          store.updateStyle('typography', 'lineHeight', '1.30');
          store.updateStyle('spacing', 'sectionGap', '8px');
          store.updateStyle('spacing', 'entryGap', '5px');
          store.updateStyle('colors', 'text', '#111827');
          store.updateStyle('colors', 'border', '#1e3a8a');
          break;

        case 'modern':
          store.updateStyle('typography', 'fontFamily', 'Inter');
          store.updateStyle('typography', 'fontSize', '9.5pt');
          store.updateStyle('typography', 'lineHeight', '1.24');
          store.updateStyle('spacing', 'sectionGap', '6px');
          store.updateStyle('spacing', 'entryGap', '4px');
          store.updateStyle('colors', 'text', '#111827');
          store.updateStyle('colors', 'border', '#2563eb');
          break;

        case 'minimalist':
          store.updateStyle('typography', 'fontFamily', 'Arial');
          store.updateStyle('typography', 'fontSize', '9pt');
          store.updateStyle('typography', 'lineHeight', '1.20');
          store.updateStyle('spacing', 'sectionGap', '5px');
          store.updateStyle('spacing', 'entryGap', '3px');
          store.updateStyle('colors', 'text', '#000000');
          store.updateStyle('colors', 'border', '#4b5563');
          break;
      }
    }

    static initAiTools() {
      AiPolishController.init();
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 9B. REAL GEMINI AI POLISH CONTROLLER (Embedded in Studio Editor)
  // ═══════════════════════════════════════════════════════════════════

  class AiPolishController {
    static currentTargetEl = null;
    static currentTargetText = '';
    static lastPolishedText = '';

    static setTarget(element, text) {
      this.currentTargetEl = element;
      this.currentTargetText = (text || (element ? element.innerText : '')).trim();
      const preview = document.getElementById('aiSelectedPreview');
      if (preview) {
        if (this.currentTargetText) {
          preview.innerText = `"${this.currentTargetText.slice(0, 120)}${this.currentTargetText.length > 120 ? '...' : ''}"`;
          preview.style.fontStyle = 'normal';
          preview.style.color = 'var(--editor-text)';
        } else {
          preview.innerText = 'Click any bullet or section on the artboard to target it.';
          preview.style.fontStyle = 'italic';
          preview.style.color = 'var(--editor-text-muted)';
        }
      }
    }

    static async runPolish(mode, customInstruction = '', btnEl = null) {
      if (!this.currentTargetText) {
        const firstBullet = document.querySelector('.bullet-item') || document.querySelector('.summary-text');
        if (firstBullet) {
          this.setTarget(firstBullet, firstBullet.innerText);
        } else {
          alert('Please click on a bullet or text block on your resume first.');
          return;
        }
      }

      const origBtnHtml = btnEl ? btnEl.innerHTML : '';
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Polishing...';
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
      store.pushSnapshot('AI Polish applied');

      const updated = this.lastPolishedText;
      this.setTarget(this.currentTargetEl, updated);

      const diffCard = document.getElementById('aiDiffCard');
      if (diffCard) diffCard.style.display = 'none';

      // Visual pulse
      this.currentTargetEl.style.transition = 'background 0.3s ease';
      this.currentTargetEl.style.background = 'rgba(16, 185, 129, 0.25)';
      setTimeout(() => {
        if (this.currentTargetEl) this.currentTargetEl.style.background = '';
      }, 1200);
    }

    static discardPolish() {
      this.lastPolishedText = '';
      const diffCard = document.getElementById('aiDiffCard');
      if (diffCard) diffCard.style.display = 'none';
    }

    static init() {
      const bMetrics = document.getElementById('aiBtnMetrics');
      if (bMetrics) bMetrics.addEventListener('click', () => this.runPolish('metrics', '', bMetrics));

      const bVerbs = document.getElementById('aiBtnVerbs');
      if (bVerbs) bVerbs.addEventListener('click', () => this.runPolish('action_verbs', '', bVerbs));

      const bAts = document.getElementById('aiBtnAts');
      if (bAts) bAts.addEventListener('click', () => this.runPolish('ats', '', bAts));

      const bConcise = document.getElementById('aiBtnConcise');
      if (bConcise) bConcise.addEventListener('click', () => this.runPolish('concise', '', bConcise));

      const bTone = document.getElementById('aiBtnTone');
      if (bTone) bTone.addEventListener('click', () => this.runPolish('tone', '', bTone));

      const bCustom = document.getElementById('aiBtnRunCustom');
      const customPrompt = document.getElementById('aiCustomPrompt');
      if (bCustom) {
        bCustom.addEventListener('click', () => {
          const inst = (customPrompt?.value || '').trim();
          if (!inst) {
            alert('Please type an instruction for the AI (e.g. "Add metrics for cloud architecture").');
            return;
          }
          this.runPolish('custom', inst, bCustom);
        });
      }

      const bApply = document.getElementById('aiBtnApply');
      if (bApply) bApply.addEventListener('click', () => this.applyPolish());

      const bDiscard = document.getElementById('aiBtnDiscard');
      if (bDiscard) bDiscard.addEventListener('click', () => this.discardPolish());

      // Auto-target when user clicks any text inside the artboard
      const artboard = document.getElementById('editorArtboard');
      if (artboard) {
        artboard.addEventListener('click', (e) => {
          const target = e.target.closest('.bullet-item, .summary-text, .section-title, .role-title, .two-col-left, .two-col-line');
          if (target && target.innerText.trim()) {
            this.setTarget(target, target.innerText);
          }
        });
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 10. ZOOM CONTROLLER (Smooth Viewport Scaling, Slider, Fit to Page)
  // ═══════════════════════════════════════════════════════════════════

  class ZoomController {
    static init() {
      const slider = document.getElementById('zoomSlider');
      const label = document.getElementById('zoomLabel');
      const btnIn = document.getElementById('btnZoomIn');
      const btnOut = document.getElementById('btnZoomOut');
      const btnFit = document.getElementById('btnZoomFit');
      const workspace = document.getElementById('editorWorkspace');

      const applyZoom = (val) => {
        val = Math.max(25, Math.min(400, Math.round(val)));
        store.state.zoom = val;
        if (slider) slider.value = val;
        if (label) label.innerText = `${val}%`;

        const viewport = document.getElementById('editorViewport');
        if (viewport) {
          viewport.style.transform = `scale(${val / 100})`;
        }
      };

      if (slider) {
        slider.addEventListener('input', () => applyZoom(slider.value));
      }

      if (btnIn) {
        btnIn.addEventListener('click', () => applyZoom(store.state.zoom + 10));
      }

      if (btnOut) {
        btnOut.addEventListener('click', () => applyZoom(store.state.zoom - 10));
      }

      // Fit to Page calculation
      if (btnFit) {
        btnFit.addEventListener('click', () => {
          if (!workspace) return;
          const artboard = document.getElementById('editorArtboard');
          if (!artboard) return;

          const wsW = workspace.clientWidth - 100; // padding buffer
          const abW = artboard.offsetWidth || 816; // 8.5in at 96 DPI
          const fitZoom = Math.round((wsW / abW) * 100);
          applyZoom(Math.max(40, Math.min(150, fitZoom)));
        });
      }

      // Ctrl + Mouse Wheel Zoom
      if (workspace) {
        workspace.addEventListener('wheel', (e) => {
          if (e.ctrlKey) {
            e.preventDefault();
            const delta = e.deltaY < 0 ? 5 : -5;
            applyZoom(store.state.zoom + delta);
          }
        }, { passive: false });
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 11. DRAG MANAGER (Block Reordering with Drop Indicator Line)
  // ═══════════════════════════════════════════════════════════════════

  class DragManager {
    static init() {
      const container = document.getElementById('resumeContent');
      if (!container) return;

      let draggedEl = null;
      let dropIndicator = null;

      // Create reusable drop indicator line
      dropIndicator = document.createElement('div');
      dropIndicator.className = 'block-drop-indicator';
      container.parentNode.appendChild(dropIndicator);

      container.addEventListener('pointerdown', (e) => {
        const handle = e.target.closest('.block-drag-handle');
        if (!handle) return;

        const block = handle.closest('.editor-block');
        if (!block) return;

        block.setAttribute('draggable', 'true');
        draggedEl = block;
      });

      container.addEventListener('dragstart', (e) => {
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
        if (draggedEl) {
          draggedEl.classList.remove('dragging');
          draggedEl.removeAttribute('draggable');
          draggedEl = null;
        }
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
          store.pushSnapshot('Reorder Blocks');
          PageOverflowDetector.check();
        }
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 12. PAGE OVERFLOW DETECTOR & AUTO-FIT CONTROLLER
  // ═══════════════════════════════════════════════════════════════════

  class PageOverflowDetector {
    static check() {
      const artboard = document.getElementById('editorArtboard');
      const counter = document.getElementById('pageCounter');
      const autoFitBtn = document.getElementById('btnAutoFit');
      if (!artboard) return;

      // 11 inches at standard 96 DPI = 1056px
      const standardPageHeight = 1056;
      const contentHeight = artboard.scrollHeight;

      if (contentHeight > standardPageHeight + 15) {
        artboard.classList.add('content-overflow');
        if (counter) {
          counter.innerText = 'Page 1 of 2 (Overflow)';
          counter.classList.add('overflow');
        }
        if (autoFitBtn) autoFitBtn.classList.add('visible');
      } else {
        artboard.classList.remove('content-overflow');
        if (counter) {
          counter.innerText = 'Page 1 of 1';
          counter.classList.remove('overflow');
        }
        if (autoFitBtn) autoFitBtn.classList.remove('visible');
      }
    }

    static initAutoFit() {
      const autoFitBtn = document.getElementById('btnAutoFit');
      if (!autoFitBtn) return;

      autoFitBtn.addEventListener('click', () => {
        // Automatically calculate and inject compact spacing
        store.updateStyle('typography', 'fontSize', '9pt');
        store.updateStyle('typography', 'lineHeight', '1.16');
        store.updateStyle('spacing', 'sectionGap', '4px');
        store.updateStyle('spacing', 'entryGap', '2.5px');
        store.updateStyle('spacing', 'bulletGap', '0.5px');
        store.updateStyle('page', 'marginTop', '0.28in');
        store.updateStyle('page', 'marginBottom', '0.28in');
        store.updateStyle('page', 'marginLeft', '0.38in');
        store.updateStyle('page', 'marginRight', '0.38in');

        // Update inputs
        const sizeInput = document.getElementById('fontSizeInput');
        if (sizeInput) sizeInput.value = 9;

        setTimeout(() => {
          PageOverflowDetector.check();
        }, 100);
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 13. AUTO-SAVER (Debounced Persistent POST to /api/editor/save)
  // ═══════════════════════════════════════════════════════════════════

  class AutoSaver {
    static init() {
      AutoSaver.debounceTimer = null;
      store.subscribe(() => {
        AutoSaver.trigger();
      });
    }

    static trigger() {
      const statusEl = document.getElementById('saveStatus');
      if (statusEl) {
        statusEl.className = 'save-status unsaved';
        statusEl.querySelector('span:not(.dot)').innerText = 'Unsaved changes';
      }

      clearTimeout(AutoSaver.debounceTimer);
      AutoSaver.debounceTimer = setTimeout(() => {
        AutoSaver.saveNow();
      }, 1500);
    }

    static async saveNow() {
      const statusEl = document.getElementById('saveStatus');
      if (statusEl) {
        statusEl.className = 'save-status saving';
        statusEl.querySelector('span:not(.dot)').innerText = 'Saving...';
      }

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

        if (resp.ok) {
          store.state.isDirty = false;
          if (statusEl) {
            statusEl.className = 'save-status';
            statusEl.querySelector('span:not(.dot)').innerText = 'Saved';
          }
        } else {
          throw new Error('Save HTTP status ' + resp.status);
        }
      } catch (err) {
        console.error('[AutoSaver] Save failed:', err);
        if (statusEl) {
          statusEl.className = 'save-status unsaved';
          statusEl.querySelector('span:not(.dot)').innerText = 'Save Error';
        }
      }
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 14. PDF EXPORTER (100% Exact Playwright Chromium Generation)
  // ═══════════════════════════════════════════════════════════════════

  class PdfExporter {
    static init() {
      const btnDownload = document.getElementById('btnDownloadPdf');
      const btnPrint = document.getElementById('btnPrintNative');

      // 1. Instant Print / Save as PDF (0 seconds, uses native browser dialog + print CSS)
      if (btnPrint) {
        btnPrint.addEventListener('click', () => {
          InlineEditor.stopEditing();
          window.print();
        });
      }

      if (!btnDownload) return;

      // 2. Headless Chromium Server Render (1:1 Playwright Vector PDF)
      btnDownload.addEventListener('click', async () => {
        InlineEditor.stopEditing();

        const origHtml = btnDownload.innerHTML;
        let seconds = 0;
        btnDownload.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Rendering PDF (<span id="pdfSec">0</span>s)...';
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
          editor_styles: store.state.styles
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
  // 15. KEYBOARD SHORTCUT MANAGER
  // ═══════════════════════════════════════════════════════════════════

  class ShortcutManager {
    static init() {
      document.addEventListener('keydown', (e) => {
        // Ctrl+Z (Undo)
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
          e.preventDefault();
          store.undo();
        }
        // Ctrl+Y or Ctrl+Shift+Z (Redo)
        else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
          e.preventDefault();
          store.redo();
        }
        // Ctrl+S (Save)
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
          e.preventDefault();
          AutoSaver.saveNow();
        }
        // Ctrl+P (Print / PDF Export)
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'p') {
          e.preventDefault();
          const btn = document.getElementById('btnDownloadPdf');
          if (btn) btn.click();
        }
        // Escape (Deselect / Cancel)
        else if (e.key === 'Escape') {
          SelectionManager.clearSelection();
        }
        // Delete block when selected and NOT typing inside editable text
        else if ((e.key === 'Delete' || e.key === 'Backspace') && store.state.selectedBlockId && !store.state.isEditing) {
          if (!['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
            e.preventDefault();
            InspectorController.deleteSelectedBlock();
          }
        }
      });
    }
  }


  // ═══════════════════════════════════════════════════════════════════
  // 16. BOOTSTRAP / INITIALIZATION
  // ═══════════════════════════════════════════════════════════════════

  document.addEventListener('DOMContentLoaded', () => {
    // 1. Read initial resume data injected by Jinja template
    let initialResume = {};
    const dataTag = document.getElementById('resumeData');
    if (dataTag && dataTag.textContent) {
      try {
        initialResume = JSON.parse(dataTag.textContent);
      } catch (err) {
        console.error('[Editor] Failed to parse injected JSON:', err);
      }
    }

    // 2. Initialize Store
    store.init(initialResume);

    // 3. Render Blocks
    BlockRenderer.renderAll(store.state.resume, store.state.styles);

    // 4. Initialize Controllers
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

    // 5. Subscribe store updates to re-render
    store.subscribe((event) => {
      if (event === 'state_restored') {
        BlockRenderer.renderAll(store.state.resume, store.state.styles);
      }
    });

    console.log('[Editor] Canva-grade PDF resume editor initialized successfully.');
  });

})();
