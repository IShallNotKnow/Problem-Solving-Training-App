import { useNavigate } from 'react-router-dom';
import { FiArrowLeft } from 'react-icons/fi';
import './LegalPages.css';

const LAST_UPDATED = '4 August 2026';
const CONTACT_EMAIL = 'privacy@studykit.dev';

const sections = [
    {
        id: 'introduction',
        title: 'Introduction',
        content: (
            <>
                <p>This Privacy Policy describes how Studykit ("we," "us," or "our") collects, uses, and discloses your personal information when you use our service at studykit.dev (the "Service").</p>
                <p>We are committed to protecting your personal information and your right to privacy. Please read this policy carefully — it explains what we collect, why we collect it, and what rights you have over it.</p>
                <p>This policy applies to all information collected through the Service and any related communications with us.</p>
            </>
        ),
    },
    {
        id: 'definitions',
        title: 'Definitions',
        content: (
            <>
                <ul>
                    <li><strong>Company</strong>: when this policy mentions "Company," "we," "us," or "our," it refers to Studykit.</li>
                    <li><strong>Device</strong>: any internet-connected device used to access the Service.</li>
                    <li><strong>Personal Data</strong>: any information that directly or indirectly allows for the identification of a natural person.</li>
                    <li><strong>Service</strong>: the Studykit web application at studykit.dev.</li>
                    <li><strong>Usage Data</strong>: data collected automatically from your use of the Service, such as IP address, browser type, and session activity.</li>
                    <li><strong>You</strong>: the individual registered with Studykit to use the Service.</li>
                </ul>
            </>
        ),
    },
    {
        id: 'data-collected',
        title: 'Information we collect',
        content: (
            <>
                <p>We collect the following categories of information:</p>
                <ul>
                    <li><strong>Account data</strong> — your email address, collected when you create an account via Supabase Auth.</li>
                    <li><strong>Study content</strong> — PDFs and notes you upload, stored securely in Supabase Storage. This content is processed by third-party AI services to generate study questions.</li>
                    <li><strong>Session data</strong> — questions generated, answers submitted, topic performance, and session progress.</li>
                    <li><strong>Usage data</strong> — your IP address (used for rate limiting), browser type, and interaction timestamps.</li>
                </ul>
                <p>We do not collect your name, phone number, postal address, or payment information. We do not use cookies for tracking or advertising purposes. We use only functional session tokens issued by Supabase Auth.</p>
            </>
        ),
    },
    {
        id: 'how-we-use',
        title: 'How we use your information',
        content: (
            <>
                <p>We use the information we collect only to provide and improve the Service:</p>
                <ul>
                    <li>To create and maintain your account and authenticate your sessions.</li>
                    <li>To generate study questions from your uploaded content using AI services.</li>
                    <li>To track your session progress and adapt question difficulty over time.</li>
                    <li>To enforce rate limits and protect the Service against abuse.</li>
                    <li>To diagnose and fix technical issues.</li>
                    <li>To communicate with you about important changes to the Service or this policy.</li>
                </ul>
                <p>We do not use your data for advertising, profiling, or sale to third parties.</p>
            </>
        ),
    },
    {
        id: 'third-parties',
        title: 'Third-party services',
        content: (
            <>
                <p>We share data with the following third-party services to operate Studykit. Each is bound by its own privacy policy:</p>
                <ul>
                    <li><strong>OpenAI</strong> — your study content and answers are sent to OpenAI to generate questions and evaluate responses. <a href="https://openai.com/policies/privacy-policy" target="_blank" rel="noopener noreferrer">OpenAI Privacy Policy</a>.</li>
                    <li><strong>Supabase</strong> — stores your account data, session data, and uploaded files. <a href="https://supabase.com/privacy" target="_blank" rel="noopener noreferrer">Supabase Privacy Policy</a>.</li>
                    <li><strong>LlamaCloud</strong> — PDFs you upload are sent to LlamaCloud for text and image extraction, then deleted from their servers after processing. <a href="https://www.llamaindex.ai/privacy" target="_blank" rel="noopener noreferrer">LlamaCloud Privacy Policy</a>.</li>
                    <li><strong>Vercel</strong> — hosts the Studykit frontend. <a href="https://vercel.com/legal/privacy-policy" target="_blank" rel="noopener noreferrer">Vercel Privacy Policy</a>.</li>
                    <li><strong>Cloudflare</strong> — provides DNS, DDoS protection, and content delivery. <a href="https://www.cloudflare.com/privacypolicy/" target="_blank" rel="noopener noreferrer">Cloudflare Privacy Policy</a>.</li>
                </ul>
                <p>We do not sell your personal data to any third party. We do not share your data with advertisers.</p>
            </>
        ),
    },
    {
        id: 'retention',
        title: 'Data retention',
        content: (
            <>
                <p>We retain your personal data only as long as necessary to provide the Service or as required by law:</p>
                <ul>
                    <li><strong>Account data</strong> — retained until you delete your account.</li>
                    <li><strong>Study sessions and content</strong> — retained until you delete the session or your account.</li>
                    <li><strong>Uploaded files</strong> — PDFs and images are deleted from storage when the associated session is deleted or your account is closed.</li>
                    <li><strong>Usage data</strong> — retained for a short period for rate limiting and diagnostic purposes.</li>
                </ul>
                <p>To request deletion of your account and all associated data, contact us at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. We will process your request within 30 days.</p>
            </>
        ),
    },
    {
        id: 'transfers',
        title: 'International data transfers',
        content: (
            <>
                <p>Studykit is based in the United States. If you access the Service from outside the United States, your information will be transferred to, stored, and processed in the United States and other countries where our service providers operate.</p>
                <p>By using the Service, you consent to the transfer of your information to countries that may have different data protection laws than your country of residence. We take steps to ensure your data is protected in accordance with this policy regardless of where it is processed.</p>
                <p>For users in the European Economic Area (EEA), we rely on appropriate safeguards for international transfers, including Standard Contractual Clauses where applicable.</p>
            </>
        ),
    },
    {
        id: 'security',
        title: 'Security',
        content: (
            <>
                <p>We implement technical and organisational measures to protect your personal data, including:</p>
                <ul>
                    <li>Row-level security on all database tables, ensuring each user can only access their own data.</li>
                    <li>JWT-based authentication required for all API requests.</li>
                    <li>HTTPS enforced for all connections.</li>
                    <li>Service role credentials restricted to server-side storage operations only.</li>
                </ul>
                <p>No method of transmission over the internet or electronic storage is 100% secure. While we use commercially reasonable measures to protect your data, we cannot guarantee absolute security. In the event of a data breach affecting your personal data, we will notify you as required by applicable law.</p>
            </>
        ),
    },
    {
        id: 'children',
        title: "Children's privacy",
        content: (
            <>
                <p>The Service is not directed to anyone under the age of 13. We do not knowingly collect personally identifiable information from children under 13. If you are a parent or guardian and believe your child has provided us with personal data without your consent, please contact us at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> and we will delete that information promptly.</p>
                <p>If you are between 13 and 18 years old, you may use the Service only with the involvement and consent of a parent or guardian.</p>
            </>
        ),
    },
    {
        id: 'your-rights',
        title: 'Your privacy rights',
        content: (
            <>
                <p>Depending on your location, you may have the following rights regarding your personal data:</p>
                <ul>
                    <li><strong>Access</strong> — request a copy of the personal data we hold about you.</li>
                    <li><strong>Correction</strong> — request that we correct inaccurate or incomplete data.</li>
                    <li><strong>Deletion</strong> — request that we delete your personal data. You can also delete sessions and your account directly through the Service.</li>
                    <li><strong>Portability</strong> — request your data in a structured, machine-readable format.</li>
                    <li><strong>Restriction</strong> — request that we restrict processing of your data in certain circumstances.</li>
                    <li><strong>Objection</strong> — object to our processing of your data where we rely on legitimate interests.</li>
                </ul>
                <p><strong>EEA and UK residents (GDPR)</strong>: you have the rights listed above and may lodge a complaint with your local data protection authority if you believe we have not complied with applicable law.</p>
                <p><strong>California residents (CCPA)</strong>: you have the right to know what personal information we collect, to request deletion, and to opt out of the sale of your personal information. We do not sell personal information. We will respond to verified requests within 45 days as required by the CCPA.</p>
                <p>To exercise any of these rights, contact us at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. We may verify your identity before processing your request.</p>
            </>
        ),
    },
    {
        id: 'changes',
        title: 'Changes to this policy',
        content: (
            <>
                <p>We may update this Privacy Policy from time to time. When we make material changes, we will notify you by email and by posting a prominent notice on the Service before the change takes effect.</p>
                <p>We encourage you to review this policy periodically. Your continued use of the Service after any changes constitutes your acceptance of the updated policy.</p>
            </>
        ),
    },
    {
        id: 'contact',
        title: 'Contact',
        content: (
            <>
                <p>If you have questions about this Privacy Policy, wish to exercise your rights, or have a privacy concern, please contact us:</p>
                <ul>
                    <li>By email: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a></li>
                    <li>By visiting: <a href="https://www.studykit.dev" target="_blank" rel="noopener noreferrer">studykit.dev</a></li>
                </ul>
                <p>We will respond to all requests within 30 days.</p>
            </>
        ),
    },
];

export default function PrivacyPage() {
    const navigate = useNavigate();

    return (
        <div className="legal-wrap">
            <header className="legal-header">
                <button
                    className="legal-back"
                    onClick={() => navigate(-1)}
                    aria-label="Go back"
                >
                    <FiArrowLeft size={16} />
                    Back
                </button>
            </header>

            <main className="legal-main">
                <div className="legal-body">
                    <div className="legal-title-block">
                        <h1>Privacy Policy</h1>
                        <p className="legal-updated">Last updated: {LAST_UPDATED}</p>
                    </div>

                    <nav className="legal-toc" aria-label="Table of contents">
                        <p className="legal-toc-label">Contents</p>
                        <ol>
                            {sections.map(s => (
                                <li key={s.id}>
                                    <a href={`#${s.id}`}>{s.title}</a>
                                </li>
                            ))}
                        </ol>
                    </nav>

                    {sections.map(s => (
                        <section key={s.id} id={s.id} className="legal-section">
                            <h2>{s.title}</h2>
                            {s.content}
                        </section>
                    ))}
                </div>
            </main>

            <footer className="legal-footer">
                <a href="/terms">Terms of Service</a>
                <span aria-hidden>·</span>
                <a href="/privacy">Privacy Policy</a>
                <span aria-hidden>·</span>
                <a href={`mailto:${CONTACT_EMAIL}`}>Contact</a>
            </footer>
        </div>
    );
}