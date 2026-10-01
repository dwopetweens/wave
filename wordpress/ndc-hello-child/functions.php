<?php
/**
 * NDC Hello Child: site-wide Elementor header/footer and the NDC logo.
 *
 * The header and footer are ordinary Elementor templates (Templates > Saved
 * Templates), so they are edited once in the visual editor and appear on every
 * page. This gives free Elementor the part of Elementor Pro's Theme Builder
 * that this site needs. If Elementor Pro is ever installed, its Theme Builder
 * header/footer take priority automatically.
 *
 * @package NDC_Hello_Child
 */

defined( 'ABSPATH' ) || exit;

define( 'NDC_CHILD_VERSION', '1.0.1' );

/** Template titles looked up when nothing is chosen in the Customizer. */
const NDC_PART_TITLES = array(
	'header' => 'NDC Site Header',
	'footer' => 'NDC Site Footer',
);

add_action(
	'wp_enqueue_scripts',
	static function () {
		wp_enqueue_style( 'ndc-hello-child', get_stylesheet_uri(), array(), NDC_CHILD_VERSION );
	},
	20
);

/* -------------------------------------------------------------------------
 * Logo shortcode: [ndc_logo variant="light|dark" height="56" height_mobile="40" link="yes"]
 * "light" is the cream logo for dark backgrounds; "dark" is the black logo.
 * ---------------------------------------------------------------------- */
add_shortcode(
	'ndc_logo',
	static function ( $atts ) {
		$a = shortcode_atts(
			array(
				'variant'       => 'light',
				'height'        => '56',
				'height_mobile' => '',
				'link'          => 'yes',
			),
			$atts,
			'ndc_logo'
		);

		$variant = 'dark' === $a['variant'] ? 'dark' : 'light';
		$height  = max( 16, min( 400, (int) $a['height'] ) );
		$mobile  = $a['height_mobile'] ? max( 16, min( 400, (int) $a['height_mobile'] ) ) : 0;
		$style   = '--ndc-logo-h:' . $height . 'px;' . ( $mobile ? '--ndc-logo-h-mobile:' . $mobile . 'px;' : '' );
		$name    = get_bloginfo( 'name' ) ? get_bloginfo( 'name' ) : 'NDC Consulting Group';

		// Source artwork is 894 x 371; width/height attributes prevent layout shift.
		$img = sprintf(
			'<img class="ndc-logo" src="%1$s" width="%2$d" height="%3$d" alt="%4$s" style="%5$s" decoding="async">',
			esc_url( get_stylesheet_directory_uri() . '/assets/img/ndc-logo-' . $variant . '.png' ),
			(int) round( $height * 894 / 371 ),
			$height,
			esc_attr( $name ),
			esc_attr( $style )
		);

		if ( 'no' === $a['link'] ) {
			return $img;
		}
		return '<a class="ndc-logo-link" href="' . esc_url( home_url( '/' ) ) . '" rel="home">' . $img . '</a>';
	}
);

/* -------------------------------------------------------------------------
 * Site header / footer from Elementor templates
 * ---------------------------------------------------------------------- */

/**
 * Find the Elementor template to use for a site part.
 *
 * @param string $part 'header' or 'footer'.
 * @return int Template post ID, or 0.
 */
function ndc_part_template_id( $part ) {
	$chosen = (int) get_theme_mod( "ndc_{$part}_template", 0 );
	if ( $chosen && 'publish' === get_post_status( $chosen ) ) {
		return $chosen;
	}
	$found = get_posts(
		array(
			'post_type'      => 'elementor_library',
			'post_status'    => 'publish',
			'title'          => NDC_PART_TITLES[ $part ],
			'posts_per_page' => 1,
			'orderby'        => 'ID',
			'order'          => 'DESC',
			'fields'         => 'ids',
			'no_found_rows'  => true,
		)
	);
	return $found ? (int) $found[0] : 0;
}

/**
 * Print a site part. Returns false if no template is available, so the
 * caller can fall back to Hello's default header/footer.
 *
 * @param string $part 'header' or 'footer'.
 * @return bool
 */
function ndc_render_part( $part ) {
	if ( ! did_action( 'elementor/loaded' ) || ! class_exists( '\Elementor\Plugin' ) ) {
		return false;
	}
	$id = ndc_part_template_id( $part );
	if ( ! $id ) {
		return false;
	}
	$html = \Elementor\Plugin::instance()->frontend->get_builder_content_for_display( $id, true );
	if ( '' === trim( (string) $html ) ) {
		return false;
	}
	$tag = 'header' === $part ? 'header' : 'footer';
	printf( '<%1$s id="site-%1$s" class="ndc-site-%1$s">%2$s</%1$s>', $tag, $html ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- Elementor output.
	return true;
}

/**
 * Hello's own header/footer, used when no NDC template exists.
 *
 * @param string $part 'header' or 'footer'.
 */
function ndc_hello_default_part( $part ) {
	if ( ! function_exists( 'hello_elementor_display_header_footer' ) || ! hello_elementor_display_header_footer() ) {
		return;
	}
	if ( did_action( 'elementor/loaded' ) && function_exists( 'hello_header_footer_experiment_active' ) && hello_header_footer_experiment_active() ) {
		get_template_part( 'template-parts/dynamic-' . $part );
	} else {
		get_template_part( 'template-parts/' . $part );
	}
}

/* -------------------------------------------------------------------------
 * Customizer: Appearance > Customize > NDC Header & Footer
 * ---------------------------------------------------------------------- */
add_action(
	'customize_register',
	static function ( WP_Customize_Manager $wp_customize ) {
		$choices = array( 0 => __( '— Automatic (by template name) —', 'ndc-hello-child' ) );
		foreach ( get_posts(
			array(
				'post_type'      => 'elementor_library',
				'post_status'    => 'publish',
				'posts_per_page' => 200,
				'orderby'        => 'title',
				'order'          => 'ASC',
			)
		) as $tpl ) {
			$choices[ $tpl->ID ] = $tpl->post_title;
		}

		$wp_customize->add_section(
			'ndc_parts',
			array(
				'title'       => __( 'NDC Header & Footer', 'ndc-hello-child' ),
				'description' => sprintf(
					/* translators: 1: header template title, 2: footer template title. */
					__( 'Choose which Elementor templates appear at the top and bottom of every page. "Automatic" uses the templates named "%1$s" and "%2$s".', 'ndc-hello-child' ),
					NDC_PART_TITLES['header'],
					NDC_PART_TITLES['footer']
				),
				'priority'    => 30,
			)
		);
		foreach ( array( 'header', 'footer' ) as $part ) {
			$wp_customize->add_setting(
				"ndc_{$part}_template",
				array(
					'default'           => 0,
					'sanitize_callback' => 'absint',
				)
			);
			$wp_customize->add_control(
				"ndc_{$part}_template",
				array(
					'section' => 'ndc_parts',
					'label'   => 'header' === $part ? __( 'Header template', 'ndc-hello-child' ) : __( 'Footer template', 'ndc-hello-child' ),
					'type'    => 'select',
					'choices' => $choices,
				)
			);
		}
	}
);
