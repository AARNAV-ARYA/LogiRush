import { Link } from "react-router-dom";

const About = () => {
  return (
    <div className="max-w-4xl mx-auto px-4 py-12">
      <h1 className="text-4xl font-bold mb-8">About LogiRush</h1>
      
      <div className="space-y-6 text-ink-secondary">
        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">
            Pan-India Logistics Intelligence Platform
          </h2>
          <p>
            LogiRush is a terrain-aware, multi-hazard logistics and accessibility intelligence
            platform for India. It began with the North Eastern Region (NER) — still its most
            detailed network — and now covers a national demonstration backbone in which each
            corridor is scored for the hazards of its own terrain: snow and landslides on the
            Himalayan passes, flooding on the Bihar and Assam floodplains, cyclones on the east
            coast, heat on the Thar, fog on the Gangetic plain. Coverage is a selected backbone
            with sample terrain data, not every road in India.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">Key Capabilities</h2>
          <ul className="list-disc list-inside space-y-2 ml-4">
            <li>Multi-objective route optimisation (time, cost, accessibility, risk, reliability)</li>
            <li>
              Terrain intelligence: eight terrain profiles, each with its own hazard weights and
              IMD-based thresholds (rainfall, heatwave, cyclone wind, fog)
            </li>
            <li>Seasonal pass closures and night-movement restrictions in the ETA</li>
            <li>Clearly labelled simulated scenarios (cyclone, heatwave, snowstorm, floods, fog)</li>
            <li>Explainable disaster prediction per road corridor</li>
            <li>
              Community incident reporting from the web console and the LogiRush Field Reporter
              app, into one shared database, with human verification before any road closes
            </li>
            <li>Deterministic accessibility scoring, recomputable by hand</li>
            <li>Shipment planning and tracking with alternative route suggestions</li>
            <li>Interactive map of the corridor network</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">Technology Stack</h2>
          <p>
            Built with modern web technologies including React, Python Flask, NetworkX for graph
            algorithms, Scikit-learn for machine learning, and Leaflet for interactive mapping.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">Where the data comes from</h2>
          <p>
            Incident reports are real: people file them from this console and from the field
            app, and they arrive in the same database. Almost everything else — corridor risk
            values, the rainfall snapshot, the model&apos;s training data — is sample or
            synthetic, and no part of this deployment reads a live IMD, GSI, CWC or ASDMA
            feed.{" "}
            <Link to="/data-sources" className="text-accent">
              Every input is listed individually
            </Link>
            , with what would replace it in a real deployment.
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold text-white mb-4">Project Context</h2>
          <p>
            This platform was developed as part of the Smart India Hackathon (SIH) initiative
            to create innovative solutions for India's infrastructure challenges. The system
            demonstrates how data-driven approaches can improve logistics reliability in
            disaster-prone regions.
          </p>
        </section>
      </div>
    </div>
  );
};

export default About;
