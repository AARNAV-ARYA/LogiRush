/*
  Required by expo-router.

  Without this file the project has no Babel preset, so Metro cannot transform JSX or resolve
  the file-based routes under app/ — the bundle fails and the app never opens on the phone.
  Its absence was why the field app could not be launched from Expo Go; nothing in app.json or
  package.json compensates for it.
*/
module.exports = function (api) {
  api.cache(true);
  return {
    presets: [["babel-preset-expo", { unstable_transformImportMeta: true }]],
  };
};
