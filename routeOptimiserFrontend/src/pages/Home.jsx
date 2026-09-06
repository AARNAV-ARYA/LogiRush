import { Link } from "react-router-dom";

const Home = () => {
  return (
    <div className="max-w-[1600px] mx-auto px-4 py-12">
      <div className="text-center mb-16">
        <h1 className="text-3xl md:text-4xl font-semibold mb-6 text-ink tracking-tight">
          LogiRush
        </h1>
        <p className="text-xl text-ink-secondary max-w-3xl mx-auto">
          NER Smart Logistics &amp; Accessibility Intelligence Platform
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-8 mb-16">
        <div className="bg-surface border border-white/10 rounded-lg p-8 hover:border-accent transition-colors">
          <h2 className="text-2xl font-semibold mb-4 text-accent">
            Disaster-Resilient Routing
          </h2>
          <p className="text-ink-secondary mb-6">
            Advanced route optimization for the North Eastern Region with real-time disaster
            prediction and accessibility scoring.
          </p>
          <Link
            to="/shipment-planner"
            className="inline-block px-6 py-3 bg-accent rounded-lg hover:brightness-110 transition-all font-semibold"
            style={{ color: 'var(--bg-contrast)' }}
          >
            Plan Shipment
          </Link>
        </div>

        <div className="bg-surface border border-white/10 rounded-lg p-8 hover:border-accent transition-colors">
          <h2 className="text-2xl font-semibold mb-4 text-accent">
            Accessibility Intelligence
          </h2>
          <p className="text-ink-secondary mb-6">
            Real-time road condition monitoring, incident tracking, and accessibility scoring
            for informed decision-making.
          </p>
          <Link
            to="/accessibility-map"
            className="inline-block px-6 py-3 bg-accent rounded-lg hover:brightness-110 transition-all font-semibold"
            style={{ color: 'var(--bg-contrast)' }}
          >
            View Map
          </Link>
        </div>
      </div>

      <div className="bg-surface border border-white/10 rounded-lg p-8">
        <h2 className="text-2xl font-semibold mb-6">Key Features</h2>
        <div className="grid md:grid-cols-3 gap-6">
          <div>
            <h3 className="text-lg font-medium mb-2 text-accent">Risk-Aware Routing</h3>
            <p className="text-ink-secondary text-sm">
              Multi-objective path finding considering time, cost, accessibility, and disaster risk.
            </p>
          </div>
          <div>
            <h3 className="text-lg font-medium mb-2 text-accent">Disaster Prediction</h3>
            <p className="text-ink-secondary text-sm">
              ML-based disruption probability for road segments using historical and live data.
            </p>
          </div>
          <div>
            <h3 className="text-lg font-medium mb-2 text-accent">Incident Management</h3>
            <p className="text-ink-secondary text-sm">
              Real-time incident reporting and impact assessment on route accessibility.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Home;
