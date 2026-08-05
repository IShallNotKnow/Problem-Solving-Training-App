export default function Footer() {
  return (
    <footer className="footer">
      <p>© 2026 Your Company</p>
      <nav>
        <Link to="/privacy">Privacy Policy</Link>
        <Link to="/terms">Terms & Conditions</Link>
        <Link to="/contact">Contact</Link>
      </nav>
    </footer>
  );
}
