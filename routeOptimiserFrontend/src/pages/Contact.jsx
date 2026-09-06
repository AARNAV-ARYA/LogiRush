const Contact = () => {
  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <h1 className="text-4xl font-bold mb-8">Contact Us</h1>
      
      <div className="bg-surface border border-white/10 rounded-lg p-8">
        <p className="text-ink-secondary mb-8">
          For questions, feedback, or support regarding the NER Logistics Intelligence Platform,
          please reach out through the following channels:
        </p>

        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-semibold mb-2">Technical Support</h2>
            <p className="text-ink-secondary">
              For technical issues or API documentation, please refer to our GitHub repository
              or contact the development team.
            </p>
          </div>

          <div>
            <h2 className="text-xl font-semibold mb-2">Project Information</h2>
            <p className="text-ink-secondary">
              This is a demonstration system developed for Smart India Hackathon (SIH).
              For official inquiries, please contact through SIH channels.
            </p>
          </div>

          <div>
            <h2 className="text-xl font-semibold mb-2">Data & Privacy</h2>
            <p className="text-ink-secondary">
              Road risk data used in this platform is synthetic for demonstration purposes.
              No real sensitive logistics data is stored or transmitted.
            </p>
          </div>
        </div>

        <div className="mt-8 p-4 bg-white/[0.06] border border-white/10 rounded">
          <p className="text-sm text-ink-muted">
            <strong>Note:</strong> This is a demonstration platform. Predictions and risk
            assessments are model-based estimates and should not be used for critical
            decision-making without validation.
          </p>
        </div>
      </div>
    </div>
  );
};

export default Contact;
