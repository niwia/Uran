export const tabStyles = `
  .uran-tabs > div > div:first-child {
    background: #0D141C;
    box-shadow: none;
    backdrop-filter: none;
  }

  .uran-tabs [role="tabpanel"] {
    padding-left: 8px !important;
    padding-right: 8px !important;
  }

  .uran-tabs .uran-tab-content {
    padding-bottom: 96px;
  }

  .uran-tabs [role="tablist"] {
    display: flex;
    flex-wrap: nowrap;
    justify-content: center;
  }

  .uran-tabs [role="tab"] {
    flex: 0 1 auto;
    min-width: 0;
    box-sizing: border-box;
    padding-left: 6px !important;
    padding-right: 6px !important;
    display: flex !important;
    align-items: center;
    justify-content: center;
  }

  .uran-tabs [role="tab"] svg {
    display: block;
    margin: 0;
  }

  .uran-tabs--content-focused [role="tablist"][aria-orientation="horizontal"],
  .uran-tabs--content-focused [role="tablist"][aria-orientation="horizontal"] > div,
  .uran-tabs--content-focused [role="tablist"][aria-orientation="horizontal"] > div > div,
  .uran-tabs--content-focused [role="tablist"][aria-orientation="horizontal"] [role="tab"] {
    animation: none !important;
    transition: none !important;
  }

  .uran-tabs--content-focused [role="tablist"][aria-orientation="horizontal"] > div > div {
    scroll-behavior: auto !important;
    scroll-snap-type: none !important;
  }

  .uran-alert-banner {
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    border: 1px solid #e55353;
    border-radius: 6px;
    background: rgba(128, 24, 24, 0.32);
    color: #ffd7d7;
  }

  .uran-accordion-body {
    background: rgba(255, 255, 255, 0.03);
    border-left: 2px solid rgba(255, 255, 255, 0.2);
    margin-left: 6px;
    margin-right: 6px;
    padding-left: 8px;
    padding-top: 4px;
    padding-bottom: 6px;
    border-radius: 0 6px 6px 0;
  }
`;
