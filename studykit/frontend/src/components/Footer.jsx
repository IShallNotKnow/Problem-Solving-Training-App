import { Link } from 'react-router-dom';

export default function Footer() {
    return (
        <footer className="footer">
            <p>© 2026 Studykit</p>
            <nav>
                <Link to="/privacy-policy">Privacy Policy</Link>
                <Link to="/terms">Terms & Conditions</Link>
                <Link to="/contact">Contact</Link>
            </nav>
        </footer>
    );
}
