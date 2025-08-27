---------------------------------------------------------------------------
-- Universidade Federal de Minas Gerais (UFMG)
---------------------------------------------------------------------------
-- Project: Generic Types
-- Design: package generic_Components
---------------------------------------------------------------------------

library IEEE;
use IEEE.STD_LOGIC_1164.all;

package GENERIC_TYPES is
    -- Define base array type with configurable word length for Reed-Solomon
    -- WORD_WIDTH_PLACEHOLDER will be replaced by build script based on RS_GF parameter
    subtype max_word is std_logic_vector(WORD_WIDTH_PLACEHOLDER downto 0);
    type std_logic_vector_array is array (natural range <>) of max_word;
    type array_of_integers is array(integer range <>) of integer;
    type integer_array is array(integer range <>) of integer;
end package GENERIC_TYPES;