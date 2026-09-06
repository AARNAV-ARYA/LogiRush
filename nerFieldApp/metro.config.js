// Expo's default Metro configuration. Present explicitly so the bundler setup is visible and
// can be extended, rather than being implicit and surprising when it needs to change.
const { getDefaultConfig } = require("expo/metro-config");

module.exports = getDefaultConfig(__dirname);
