if (!process.env.APP_GREETING) {
  throw new Error("Required environment variable APP_GREETING is missing");
}
export default {};
