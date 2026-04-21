export function inyectarEstilos(color) {
  const css = document.createElement("style");
  css.textContent = `
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    #ia-w-container * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: 'Inter', -apple-system, sans-serif;
    }

    #ia-w-btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 64px;
      height: 64px;
      border-radius: 50%;
      background: ${color};
      color: #fff;
      border: none;
      cursor: pointer;
      font-size: 28px;
      box-shadow: 0 6px 24px rgba(0,0,0,0.25);
      z-index: 100000;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    #ia-w-btn:hover {
      transform: scale(1.08);
      box-shadow: 0 8px 32px rgba(0,0,0,0.35);
    }
    #ia-w-btn.abierto { transform: rotate(180deg); }

    #ia-w-badge {
      position: fixed;
      bottom: 80px;
      right: 24px;
      background: #fff;
      color: #333;
      padding: 10px 16px;
      border-radius: 12px 12px 0 12px;
      font-size: 14px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.12);
      z-index: 99998;
      max-width: 220px;
      animation: ia-slide-up 0.5s ease;
    }

    #ia-w-chat {
      position: fixed;
      bottom: 100px;
      right: 24px;
      width: 440px;
      height: 700px;
      background: #fff;
      border-radius: 20px;
      box-shadow: 0 12px 48px rgba(0,0,0,0.2);
      z-index: 99999;
      display: none;
      flex-direction: column;
      overflow: hidden;
      animation: ia-slide-up 0.3s ease;
    }
    #ia-w-chat.visible { display: flex; }

    #ia-w-header {
      background: ${color};
      color: #fff;
      padding: 18px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-shrink: 0;
    }
    #ia-w-header-info {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    #ia-w-header-info span:first-child { font-size: 24px; }
    #ia-w-header-info div p:first-child { font-weight: 600; font-size: 15px; }
    #ia-w-header-info div p:last-child { font-size: 12px; opacity: 0.85; }
    #ia-w-close {
      background: rgba(255,255,255,0.2);
      border: none;
      color: #fff;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      cursor: pointer;
      font-size: 16px;
      transition: background 0.2s;
    }
    #ia-w-close:hover { background: rgba(255,255,255,0.35); }

    #ia-w-msgs {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: #f7f8fa;
    }
    #ia-w-msgs::-webkit-scrollbar { width: 5px; }
    #ia-w-msgs::-webkit-scrollbar-thumb { background: #ccc; border-radius: 4px; }

    .ia-msg {
      max-width: 82%;
      padding: 8px 16px !important;
      min-width: 80px;
      border-radius: 16px;
      font-size: 14px;
      line-height: 1.5;
      animation: ia-fade-in 0.3s ease;
      word-wrap: break-word;
    }
    .ia-msg.bot {
      background: #fff;
      color: #333;
      align-self: flex-start;
      border-bottom-left-radius: 4px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .ia-msg.user {
      padding: 10px 18px;
      background: ${color};
      color: #fff;
      align-self: flex-end;
      border-bottom-right-radius: 4px;
    }
    .ia-msg.typing {
      background: #fff;
      align-self: flex-start;
      border-bottom-left-radius: 4px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .ia-dots { display: flex; gap: 4px; padding: 4px 0; }
    .ia-dots span {
      width: 8px; height: 8px; background: #999;
      border-radius: 50%;
      animation: ia-dot-pulse 1.4s ease-in-out infinite;
    }
    .ia-dots span:nth-child(2) { animation-delay: 0.2s; }
    .ia-dots span:nth-child(3) { animation-delay: 0.4s; }

    /* ======= FORMULARIO ======= */
    .ia-form-card {
      width: 100%;
      min-height: 320px !important;
      display: flex;
      flex-direction: column;
      max-width: 100%;
      background: #fff;
      border-radius: 18px;
      align-self: flex-start;
      box-shadow: 0 4px 24px rgba(0,0,0,0.1);
      border: 1px solid #e8edf2;
      animation: ia-fade-in 0.4s ease;
      overflow: hidden;
    }
    .ia-form-header {
      background: linear-gradient(135deg, ${color}, ${color}dd);
      padding: 12px 20px;
      color: #fff;
      text-align: center;
    }
    .ia-form-header h4 { font-size: 15px; font-weight: 700; margin-bottom: 2px; }
    .ia-form-header p { font-size: 11px; opacity: 0.85; }

    .ia-form-progress {
      display: flex;
      justify-content: center;
      gap: 8px;
      padding: 8px 20px 0;
    }
    .ia-form-step-dot {
      width: 9px; height: 9px; border-radius: 50%;
      background: #e0e4ea; transition: all 0.3s ease;
    }
    .ia-form-step-dot.active { background: ${color}; transform: scale(1.3); }
    .ia-form-step-dot.done { background: #22c55e; }

    .ia-form-body {
      padding: 14px 20px 16px;
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
    }
    .ia-form-body::-webkit-scrollbar { width: 4px; }
    .ia-form-body::-webkit-scrollbar-thumb { background: #ddd; border-radius: 4px; }

    .ia-form-step { display: none; animation: ia-fade-in 0.3s ease; }
    .ia-form-step.active { display: flex; flex-direction: column; flex: 1; }

    .ia-form-label {
      display: block; font-size: 14px; font-weight: 600;
      color: #444; margin-bottom: 10px; letter-spacing: 0.2px;
    }
    .ia-form-card input,
    .ia-form-card select {
      width: 100%; padding: 16px 18px; margin-bottom: 16px;
      border: 1.5px solid #e0e4ea; border-radius: 14px; font-size: 15px;
      background: #fafbfc; color: #333; transition: all 0.2s ease;
      outline: none; -webkit-appearance: none;
    }
    .ia-form-card input:focus,
    .ia-form-card select:focus {
      border-color: ${color};
      box-shadow: 0 0 0 3px ${color}22;
      background: #fff;
    }
    .ia-form-card input::placeholder { color: #a0aec0; font-size: 14px; }

    .ia-time-grid {
      display: grid; grid-template-columns: repeat(3, 1fr);
      gap: 10px; margin-bottom: 16px; max-height: 140px;
      overflow-y: auto; padding-right: 4px;
    }
    .ia-time-grid::-webkit-scrollbar { width: 4px; }
    .ia-time-grid::-webkit-scrollbar-thumb { background: #ddd; border-radius: 4px; }
    .ia-time-slot {
      padding: 14px 10px; border: 1.5px solid #e0e4ea; border-radius: 12px;
      text-align: center; font-size: 14px; font-weight: 500;
      cursor: pointer; transition: all 0.2s ease; background: #fafbfc; color: #333;
    }
    .ia-time-slot:hover { border-color: ${color}; background: ${color}08; }
    .ia-time-slot.selected {
      background: ${color}; color: #fff; border-color: ${color};
      box-shadow: 0 2px 8px ${color}44;
    }
    .ia-time-slot.disabled {
      opacity: 0.35; cursor: not-allowed; text-decoration: line-through; background: #f0f0f0;
    }
    .ia-time-slot.disabled:hover { border-color: #e0e4ea; background: #f0f0f0; }
    .ia-slot-status { font-size: 10px; display: block; margin-top: 3px; }

    .ia-form-actions {
      display: flex; gap: 12px; margin-top: auto !important; padding-top: 12px;
    }
    .ia-form-btn {
      flex: 1; padding: 16px; border: none; border-radius: 14px;
      font-size: 15px; font-weight: 600; cursor: pointer;
      transition: all 0.2s ease; letter-spacing: 0.3px;
    }
    .ia-form-btn.primary {
      background: ${color}; color: #fff; box-shadow: 0 4px 12px ${color}44;
    }
    .ia-form-btn.primary:hover {
      transform: translateY(-1px); box-shadow: 0 6px 18px ${color}55;
    }
    .ia-form-btn.secondary { background: #f0f2f5; color: #555; }
    .ia-form-btn.secondary:hover { background: #e4e7eb; }
    .ia-form-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }

    .ia-loading-slots { text-align: center; padding: 30px 0; color: #999; font-size: 14px; }
    .ia-spinner {
      width: 30px; height: 30px; border: 3px solid #e0e4ea;
      border-top-color: ${color}; border-radius: 50%;
      animation: ia-spin 0.7s linear infinite; margin: 0 auto 12px;
    }

    .ia-resumen {
      background: #f8fafc; border-radius: 14px; padding: 18px;
      margin-bottom: 16px; border: 1px solid #e8edf2;
    }
    .ia-resumen-row {
      display: flex; justify-content: space-between; padding: 10px 0;
      font-size: 14px; border-bottom: 1px solid #f0f2f5;
    }
    .ia-resumen-row:last-child { border: none; }
    .ia-resumen-row span:first-child { color: #888; }
    .ia-resumen-row span:last-child { font-weight: 600; color: #333; }

    .ia-form-success { text-align: center; padding: 36px 24px; }
    .ia-form-success .ia-check {
      width: 64px; height: 64px; border-radius: 50%; background: #22c55e;
      color: #fff; font-size: 32px; display: flex; align-items: center;
      justify-content: center; margin: 0 auto 18px; animation: ia-fade-in 0.4s ease;
    }
    .ia-form-success h4 { font-size: 18px; color: #1a1a2e; margin-bottom: 8px; }
    .ia-form-success p { font-size: 14px; color: #888; }

    #ia-w-input-area {
      padding: 14px 16px; border-top: 1px solid #eee;
      display: flex; gap: 10px; background: #fff; flex-shrink: 0;
    }
    #ia-w-input {
      flex: 1; padding: 12px 16px; border: 1.5px solid #e0e0e0;
      border-radius: 24px; font-size: 14px; outline: none; transition: border-color 0.2s;
    }
    #ia-w-input:focus { border-color: ${color}; }
    #ia-w-send {
      width: 44px; height: 44px; border-radius: 50%; background: ${color};
      color: #fff; border: none; cursor: pointer; font-size: 18px;
      transition: opacity 0.2s; display: flex; align-items: center; justify-content: center;
    }
    #ia-w-send:hover { opacity: 0.85; }
    #ia-w-send:disabled { opacity: 0.5; cursor: not-allowed; }

    #ia-w-powered {
      text-align: center; padding: 6px; font-size: 11px;
      color: #aaa; background: #fff; flex-shrink: 0;
    }

    @keyframes ia-slide-up {
      from { opacity: 0; transform: translateY(16px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes ia-fade-in {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes ia-dot-pulse {
      0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
      40% { transform: scale(1); opacity: 1; }
    }
    @keyframes ia-spin { to { transform: rotate(360deg); } }

    @media (max-width: 500px) {
      #ia-w-chat {
        width: calc(100vw - 16px); height: calc(100vh - 120px);
        right: 8px; bottom: 88px; border-radius: 16px;
      }
    }
  `;
  document.head.appendChild(css);
}