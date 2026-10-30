export default function Home() {
  return (
    <main>
      <header>
        <a href="/" aria-label="FORMA home">
          FORMA
        </a>
        <span>Workbench preview</span>
      </header>
      <section aria-labelledby="intro">
        <h1 id="intro">Turn what you have into what you need.</h1>
        <p>
          Make a small tabletop stand from measured, reused sheet materials.
          Follow a visual manual and review a revised plan when the build
          changes.
        </p>
        <aside aria-label="Availability">
          Project creation is being built. Inventory, assembly instructions and
          repair review are not available yet.
        </aside>
      </section>
      <section aria-labelledby="prepare">
        <h2 id="prepare">Before you build</h2>
        <ol>
          <li>Gather your sheet materials, connectors and hand tools.</li>
          <li>
            Measure each sheet’s width, height and thickness with a ruler.
          </li>
          <li>Keep unknown measurements open until you can confirm them.</li>
        </ol>
        <p className="scope">
          FORMA starts with small desktop fixtures. Physical fit and stability
          require hands-on checks before use.
        </p>
      </section>
    </main>
  );
}
