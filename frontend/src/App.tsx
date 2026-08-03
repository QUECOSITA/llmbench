export function App() {
  return (
    <div className="instrument">
      <header className="instrument-header">
        <span className="wordmark">LLM&nbsp;BENCH</span>
        <span className="hardware-line">GPU — · RAM —</span>
      </header>
      <main>
        <section className="panel">
          <span className="panel-cap">01 · MODEL INPUT</span>
          <p>Enter a Hugging Face model link or user/model.</p>
        </section>
      </main>
    </div>
  );
}
