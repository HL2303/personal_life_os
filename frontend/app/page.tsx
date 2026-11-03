import styles from "./page.module.css";

export default function Home() {
  return (
    <main>
      <section>
        <p>Personal Life OS</p>
        <h1>A foundation for living with intention.</h1>
        <p>
          Your workspace is ready. The core product experience will take shape in the next phase.
        </p>
        <span className={styles.status}>Phase 0 foundation</span>
      </section>
    </main>
  );
}
