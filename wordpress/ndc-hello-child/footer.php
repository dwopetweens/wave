<?php
/**
 * Footer: the NDC Elementor footer template, then the closing tags.
 *
 * @package NDC_Hello_Child
 */

defined( 'ABSPATH' ) || exit;

// Elementor Pro Theme Builder first, then the NDC template, then Hello's default.
if ( ! function_exists( 'elementor_theme_do_location' ) || ! elementor_theme_do_location( 'footer' ) ) {
	if ( ! ndc_render_part( 'footer' ) ) {
		ndc_hello_default_part( 'footer' );
	}
}
?>

<?php wp_footer(); ?>

</body>
</html>
