import { useState } from "react";
import { useNavigate } from "react-router-dom";

const Signup = () => {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
  });
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");

    if (!formData.name || !formData.email || !formData.password) {
      setError("Please fill in all fields");
      return;
    }

    if (formData.password !== formData.confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    // Demo mode - just navigate to login
    navigate("/login");
  };

  return (
    <div className="max-w-md mx-auto px-4 py-12">
      <div className="bg-surface border border-white/10 rounded-lg p-8">
        <h1 className="text-3xl font-bold mb-6 text-center">Sign Up</h1>
        
        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-2">
              Full Name
            </label>
            <input
              id="name"
              name="name"
              type="text"
              value={formData.name}
              onChange={handleChange}
              className="w-full px-4 py-2 bg-white/[0.06] border border-white/10 rounded-lg focus:outline-none focus:border-accent"
              placeholder="John Doe"
            />
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-2">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              value={formData.email}
              onChange={handleChange}
              className="w-full px-4 py-2 bg-white/[0.06] border border-white/10 rounded-lg focus:outline-none focus:border-accent"
              placeholder="your@email.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium mb-2">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              value={formData.password}
              onChange={handleChange}
              className="w-full px-4 py-2 bg-white/[0.06] border border-white/10 rounded-lg focus:outline-none focus:border-accent"
              placeholder="••••••••"
            />
          </div>

          <div>
            <label htmlFor="confirmPassword" className="block text-sm font-medium mb-2">
              Confirm Password
            </label>
            <input
              id="confirmPassword"
              name="confirmPassword"
              type="password"
              value={formData.confirmPassword}
              onChange={handleChange}
              className="w-full px-4 py-2 bg-white/[0.06] border border-white/10 rounded-lg focus:outline-none focus:border-accent"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="state-error text-sm">{error}</div>
          )}

          <button
            type="submit"
            className="w-full px-6 py-3 bg-accent text-white rounded-lg hover:brightness-110 transition-all font-semibold"
            style={{ color: 'var(--bg-contrast)' }}
          >
            Sign Up
          </button>
        </form>

        <p className="mt-6 text-center text-ink-secondary text-sm">
          Demo mode: Registration will redirect to login
        </p>
      </div>
    </div>
  );
};

export default Signup;
