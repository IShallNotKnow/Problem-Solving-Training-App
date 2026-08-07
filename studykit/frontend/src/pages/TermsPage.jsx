import { useNavigate } from 'react-router-dom';
import { FiArrowLeft } from 'react-icons/fi';
import './LegalPages.css';

const LAST_UPDATED = '6 August 2026';
const CONTACT_EMAIL = 'legal@studykit.dev';

const sections = [
    {
        id: 'introduction',
        title: 'Introduction',
        content: (
            <>
                <p>These Terms of Service ("Terms") govern your access to and use of the Studykit web application at studykit.dev (the "Service"), operated by Studykit ("we," "us," or "our").</p>
                <p>By creating an account or using the Service, you confirm that you have read, understood, and agree to be bound by these Terms and our <a href="/privacy">Privacy Policy</a>, which is incorporated by reference. If you do not agree, you may not access or use the Service.</p>
            </>
        ),
    },
    {
        id: 'eligibility',
        title: 'Eligibility',
        content: (
            <>
                <p>To use the Service you must be at least 13 years old. If you are under 18, you represent that you have your parent or guardian's consent to use the Service and agree to these Terms.</p>
                <p>By using the Service, you represent and warrant that you meet these eligibility requirements and that all information you provide is accurate and complete.</p>
            </>
        ),
    },
    {
        id: 'accounts',
        title: 'User accounts',
        content: (
            <>
                <p>You must create an account to access the Service. You are responsible for:</p>
                <ul>
                    <li>Providing accurate and current information when registering.</li>
                    <li>Maintaining the confidentiality of your password and account credentials.</li>
                    <li>All activities that occur under your account.</li>
                    <li>Notifying us immediately at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> of any unauthorised access or security breach.</li>
                </ul>
                <p>We reserve the right to suspend or terminate accounts that violate these Terms or that we reasonably believe pose a security risk to the Service or other users.</p>
            </>
        ),
    },
    {
        id: 'service-description',
        title: 'Service description',
        content: (
            <>
                <p>Studykit is an AI-powered study tool that converts uploaded documents and notes into adaptive practice questions. The Service uses third-party AI models to generate questions, validate answers, and provide study assistance.</p>
                <p>We make reasonable efforts to keep the Service available 24 hours a day, 7 days a week, but we do not guarantee uninterrupted access. We may suspend the Service for maintenance, upgrades, or to address security concerns, with or without advance notice. We will use reasonable efforts to schedule planned downtime during off-peak hours.</p>
                <p>The Service is provided for personal, non-commercial educational use. Features and functionality may change over time as we improve the Service.</p>
            </>
        ),
    },
    {
        id: 'acceptable-use',
        title: 'Acceptable use',
        content: (
            <>
                <p>You agree to use the Service only for lawful purposes and in accordance with these Terms. You must not:</p>
                <ul>
                    <li>Use the Service for any illegal or unauthorised purpose.</li>
                    <li>Upload content that infringes the intellectual property rights of others, including copyrighted course materials where you do not have the right to reproduce them.</li>
                    <li>Upload content that is unlawful, harmful, defamatory, obscene, or otherwise objectionable.</li>
                    <li>Attempt to bypass any security or authentication measures.</li>
                    <li>Use automated scripts, bots, or scrapers to interact with the Service.</li>
                    <li>Interfere with or disrupt the Service or its infrastructure.</li>
                    <li>Share your account credentials or allow others to use your account.</li>
                    <li>Reverse engineer, decompile, or disassemble any part of the Service.</li>
                    <li>Use the Service to train or improve competing AI models.</li>
                </ul>
                <p>We reserve the right to remove content and suspend access without notice for violations of this section.</p>
            </>
        ),
    },
    {
        id: 'user-content',
        title: 'Your content',
        content: (
            <>
                <p>You retain all ownership rights to content you upload to the Service ("User Content"), including PDFs, notes, and any other materials.</p>
                <p>By uploading User Content, you grant us a limited, non-exclusive, royalty-free licence to process, store, and transmit your content solely as necessary to provide the Service to you. This includes sending your content to third-party AI services as described in our Privacy Policy.</p>
                <p>You represent and warrant that:</p>
                <ul>
                    <li>You own or have the necessary rights to upload and use your User Content.</li>
                    <li>Your User Content does not infringe the rights of any third party.</li>
                    <li>Your User Content complies with these Terms and applicable law.</li>
                </ul>
                <p>We do not claim ownership over your User Content and do not use it to train AI models.</p>
            </>
        ),
    },
    {
        id: 'intellectual-property',
        title: 'Intellectual property',
        content: (
            <>
                <p>The Service, including its design, code, branding, and all content generated by Studykit (excluding your User Content), is the exclusive property of Studykit and is protected by copyright, trademark, and other applicable laws.</p>
                <p>We grant you a limited, non-exclusive, non-transferable, revocable licence to use the Service for personal, non-commercial educational purposes in accordance with these Terms. This licence does not include the right to:</p>
                <ul>
                    <li>Copy, modify, or distribute any part of the Service.</li>
                    <li>Use our trademarks, logos, or branding without prior written consent.</li>
                    <li>Sublicense or resell access to the Service.</li>
                    <li>Remove or alter any copyright or proprietary notices.</li>
                </ul>
            </>
        ),
    },
    {
        id: 'ai-content',
        title: 'AI-generated content',
        content: (
            <>
                <p>Questions, feedback, and other content generated by the Service are produced by AI models and may contain errors, inaccuracies, or omissions. AI-generated content is provided for study assistance only and should not be relied upon as a substitute for professional academic guidance.</p>
                <p>We make no representations about the accuracy, completeness, or suitability of AI-generated content for any specific academic purpose. You are responsible for verifying the accuracy of any content before relying on it.</p>
            </>
        ),
    },
    {
        id: 'third-party',
        title: 'Third-party services',
        content: (
            <>
                <p>The Service integrates with third-party services including OpenAI, Supabase, LlamaCloud, Vercel, and Cloudflare. Your use of these services through Studykit is subject to their respective terms of service and privacy policies.</p>
                <p>We are not responsible for the availability, accuracy, or practices of any third-party service. We do not endorse and are not liable for any third-party content, products, or services accessible through the Service.</p>
            </>
        ),
    },
    {
        id: 'disclaimers',
        title: 'Disclaimers',
        content: (
            <>
                <p>TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, AND NON-INFRINGEMENT.</p>
                <p>WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE, OR SECURE, THAT DEFECTS WILL BE CORRECTED, OR THAT THE SERVICE OR THE SERVERS THAT MAKE IT AVAILABLE ARE FREE OF VIRUSES OR OTHER HARMFUL COMPONENTS.</p>
            </>
        ),
    },
    {
        id: 'liability',
        title: 'Limitation of liability',
        content: (
            <>
                <p>TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, STUDYKIT AND ITS OFFICERS, DIRECTORS, EMPLOYEES, AND AFFILIATES SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING BUT NOT LIMITED TO LOSS OF DATA, LOSS OF PROFITS, OR LOSS OF GOODWILL, ARISING OUT OF OR IN CONNECTION WITH YOUR USE OF OR INABILITY TO USE THE SERVICE.</p>
                <p>IN NO EVENT SHALL OUR TOTAL LIABILITY TO YOU EXCEED THE GREATER OF (A) THE AMOUNT YOU PAID US IN THE TWELVE MONTHS PRECEDING THE CLAIM, OR (B) ONE HUNDRED DOLLARS (USD $100).</p>
                <p>SOME JURISDICTIONS DO NOT ALLOW THE EXCLUSION OR LIMITATION OF LIABILITY FOR CONSEQUENTIAL OR INCIDENTAL DAMAGES, SO THE ABOVE LIMITATION MAY NOT APPLY TO YOU.</p>
            </>
        ),
    },
    {
        id: 'indemnification',
        title: 'Indemnification',
        content: (
            <>
                <p>You agree to indemnify, defend, and hold harmless Studykit and its officers, directors, employees, and affiliates from and against any claims, liabilities, damages, losses, costs, and expenses (including reasonable legal fees) arising out of or relating to your violation of these Terms, your User Content, or your use of the Service.</p>
            </>
        ),
    },
    {
        id: 'termination',
        title: 'Termination',
        content: (
            <>
                <p>We may suspend or terminate your access to the Service at our sole discretion, with or without notice, for conduct that violates these Terms or is otherwise harmful to other users, us, or third parties.</p>
                <p>You may terminate your account at any time by deleting it through the Service or by contacting us at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.</p>
                <p>Upon termination, your licence to use the Service ceases immediately. Sections 6, 7, 10, 11, 12, and 15 of these Terms survive termination.</p>
            </>
        ),
    },
    {
        id: 'governing-law',
        title: 'Governing law and disputes',
        content: (
            <>
                <p>These Terms are governed by the laws of the United States, without regard to conflict of law provisions. Any disputes arising from these Terms or your use of the Service will be resolved in the courts of competent jurisdiction in the United States.</p>
                <p>Before initiating any formal dispute, you agree to contact us at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> and attempt to resolve the matter informally. We will attempt to resolve disputes within 30 days of receiving notice.</p>
            </>
        ),
    },
    {
        id: 'changes',
        title: 'Changes to these Terms',
        content: (
            <>
                <p>We may update these Terms from time to time. When we make material changes, we will notify you by email and by posting a prominent notice on the Service before the change takes effect. The updated Terms will be effective as of the date indicated at the top of this page.</p>
                <p>Your continued use of the Service after any changes constitutes your acceptance of the revised Terms. If you do not agree to the revised Terms, you must stop using the Service.</p>
            </>
        ),
    },
    {
        id: 'general',
        title: 'General provisions',
        content: (
            <>
                <p><strong>Entire agreement</strong>: these Terms, together with our Privacy Policy, constitute the entire agreement between you and Studykit regarding the Service and supersede any prior agreements.</p>
                <p><strong>Severability</strong>: if any provision of these Terms is found to be invalid or unenforceable, the remaining provisions will continue in full force and effect.</p>
                <p><strong>Waiver</strong>: our failure to enforce any right or provision of these Terms will not constitute a waiver of that right or provision.</p>
                <p><strong>Assignment</strong>: you may not assign or transfer your rights under these Terms without our prior written consent. We may assign our rights without restriction.</p>
                <p><strong>Force majeure</strong>: we will not be liable for any delay or failure to perform resulting from causes outside our reasonable control, including acts of God, war, pandemic, or infrastructure failure.</p>
            </>
        ),
    },
    {
        id: 'contact',
        title: 'Contact',
        content: (
            <>
                <p>If you have questions about these Terms, please contact us:</p>
                <ul>
                    <li>By email: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a></li>
                    <li>By visiting: <a href="https://www.studykit.dev" target="_blank" rel="noopener noreferrer">studykit.dev</a></li>
                </ul>
            </>
        ),
    },
];

export default function TermsPage() {
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
                        <h1>Terms of Service</h1>
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